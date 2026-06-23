import json
import logging
import re
from pathlib import Path
from typing import Dict, Any, Tuple, Optional, List
from datetime import datetime, timedelta
from difflib import SequenceMatcher

import requests
from config import OLLAMA_API_URL, MODEL_NAME, FAQ_FILE_PATH, BASE_DIR

logger = logging.getLogger(__name__)


class LLMConnectionError(Exception):
    pass


class ConversationMemory:
    def __init__(self, max_history: int = 6):
        self.history: List[Dict[str, str]] = []
        self.max_history = max_history

    def add(self, question: str, answer: str):
        self.history.append({"question": question, "answer": answer, "timestamp": datetime.now().isoformat()})
        if len(self.history) > self.max_history:
            self.history.pop(0)

    def get_context(self, current_question: str) -> str:
        if not self.history:
            return ""
        lines = ["### Recent Conversation History:"]
        for entry in self.history[-3:]:
            lines.append(f"Student: {entry['question']}")
            first_line = entry['answer'].split('\n')[0][:100]
            lines.append(f"Assistant: {first_line}")
        return "\n".join(lines)

    def detect_topic(self) -> Optional[str]:
        if not self.history:
            return None
        return self.history[-1].get("topic")

    def get_topic(self, question: str) -> str:
        topics = {
            "registration": ["register", "course", "enrol", "add", "drop", "semester", "subject"],
            "examination": ["exam", "test", "cheat", "grade", "gpa", "score", "fail", "pass"],
            "fee": ["fee", "payment", "tuition", "bank", "pay", "invoice", "cost", "money"],
            "hostel": ["hostel", "room", "accommodation", "hall", "dorm", "housing"],
            "library": ["library", "book", "borrow", "journal", "database", "study"],
            "ict": ["wifi", "internet", "email", "portal", "password", "computer", "ict"],
            "calendar": ["calendar", "date", "deadline", "holiday", "break", "semester"],
            "graduation": ["graduate", "graduation", "degree", "certificate", "transcript"],
            "conduct": ["conduct", "disciplinary", "dress", "behaviour", "harassment"],
            "admission": ["admission", "apply", "accept", "offer", "intake"],
        }
        q = question.lower()
        scores = {}
        for topic, keywords in topics.items():
            score = sum(1 for kw in keywords if kw in q)
            if score > 0:
                scores[topic] = score
        if scores:
            return max(scores, key=scores.get)
        return "general"

    def would_repeat(self, question: str) -> Tuple[bool, Optional[str]]:
        for entry in self.history[-2:]:
            similarity = SequenceMatcher(None, question.lower(), entry["question"].lower()).ratio()
            if similarity > 0.85:
                return True, entry["answer"]
        return False, None


class SemanticCache:
    def __init__(self, ttl_minutes: int = 30):
        self.cache: Dict[str, Tuple[Any, datetime]] = {}
        self.ttl = timedelta(minutes=ttl_minutes)

    def _normalize(self, text: str) -> str:
        return re.sub(r'\s+', ' ', text.lower().strip())

    def get(self, question: str) -> Optional[Any]:
        normalized = self._normalize(question)
        for key, (value, timestamp) in list(self.cache.items()):
            if datetime.now() - timestamp > self.ttl:
                del self.cache[key]
                continue
            similarity = SequenceMatcher(None, normalized, key).ratio()
            if similarity > 0.92:
                logger.info(f"Semantic cache hit (similarity: {similarity:.2f})")
                return value
        return None

    def set(self, question: str, value: Any):
        key = self._normalize(question)
        self.cache[key] = (value, datetime.now())
        if len(self.cache) > 100:
            oldest = min(self.cache.keys(), key=lambda k: self.cache[k][1])
            del self.cache[oldest]


class LLMClient:
    def __init__(self):
        self.api_url = OLLAMA_API_URL
        self.model = MODEL_NAME
        self.faq_db = self._load_faq_database()
        self.knowledge_base = self._load_knowledge_base()
        self.memory = ConversationMemory()
        self.cache = SemanticCache()
        self.kb_index = self._build_kb_index()

    def _load_faq_database(self) -> list:
        try:
            if FAQ_FILE_PATH.exists():
                with open(FAQ_FILE_PATH, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get("university_faqs", [])
            return []
        except Exception as e:
            logger.error(f"Error loading FAQ database: {e}")
            return []

    def _load_knowledge_base(self) -> Dict[str, str]:
        kb_path = BASE_DIR.parent / "knowledge-base"
        docs = {}
        if not kb_path.exists():
            logger.warning(f"Knowledge base directory not found at {kb_path}")
            return docs
        for md_file in sorted(kb_path.glob("*.md")):
            try:
                content = md_file.read_text(encoding="utf-8")
                name = md_file.stem.replace("-", " ").title()
                docs[name] = content
                logger.info(f"Loaded knowledge document: {name}")
            except Exception as e:
                logger.error(f"Error loading {md_file.name}: {e}")
        return docs

    def _build_kb_index(self) -> List[Dict[str, Any]]:
        index = []
        for doc_name, content in self.knowledge_base.items():
            sections = re.split(r'\n## ', content)
            for section in sections:
                lines = section.strip().split('\n')
                title = lines[0].replace('#', '').strip()
                body = '\n'.join(lines[1:]).strip()
                words = set(re.findall(r'\b[a-z]{4,}\b', (title + ' ' + body[:500]).lower()))
                index.append({
                    "doc": doc_name,
                    "section": title,
                    "content": section.strip(),
                    "keywords": words
                })
        return index

    def retrieve_context(self, question: str) -> Tuple[Optional[str], Optional[str], List[str], float]:
        question_lower = question.lower()
        search_terms = set(re.findall(r'\b[a-z]{3,}\b', question_lower))

        # 1. Search FAQ database (keyword matching)
        matched_faqs = []
        matched_category = None
        for faq in self.faq_db:
            for keyword in faq.get("keywords", []):
                if keyword in question_lower:
                    matched_faqs.append(faq)
                    matched_category = matched_category or faq.get("category")
                    break

        # 2. Search knowledge base documents (full-text relevance scoring)
        kb_matches = []
        for entry in self.kb_index:
            overlap = search_terms & entry["keywords"]
            if overlap:
                score = len(overlap) / max(len(search_terms), 1)
                kb_matches.append((score, entry["doc"], entry["section"], entry["content"]))

        kb_matches.sort(reverse=True)
        top_kb = kb_matches[:3]

        # 3. Build combined context
        context_parts = []
        sources = []

        if matched_faqs:
            for faq in matched_faqs[:2]:
                context_parts.append(
                    f"[FAQ - {faq['category'].upper()}]\n"
                    f"Q: {faq['question']}\n"
                    f"A: {faq['answer']}"
                )
                sources.append(f"UDSM FAQ - {faq['category'].title()}")

        for score, doc, section, content in top_kb:
            header = f"=== {doc}: {section} ==="
            context_parts.append(f"[{doc} - {section}]\n{content[:1200]}")
            sources.append(f"{doc}")
            matched_category = matched_category or doc

        if context_parts:
            return "\n\n".join(context_parts), matched_category or "General", sources, min(len(kb_matches) / 3 + 0.3, 1.0)

        # 3. Fallback: keyword-based section search
        for doc_name, content in self.knowledge_base.items():
            sections = re.split(r'\n## ', content)
            for section in sections:
                section_lower = section.lower()
                match_count = sum(1 for term in search_terms if term in section_lower)
                if match_count >= 2:
                    context_parts.append(f"[{doc_name}]\n{section[:1500]}")
                    sources.append(doc_name)
                    matched_category = doc_name

        if context_parts:
            return "\n\n".join(context_parts[:3]), matched_category or "General", sources[:3], 0.6

        return None, None, [], 0.0

    def faq_direct_answer(self, question: str) -> Tuple[Optional[str], Optional[str], float]:
        question_lower = question.lower()
        best_match = None
        best_score = 0.0

        for faq in self.faq_db:
            faq_keywords = ' '.join(faq.get("keywords", []))
            q_similarity = SequenceMatcher(None, question_lower, faq["question"].lower()).ratio()
            kw_score = sum(1 for kw in faq.get("keywords", []) if kw in question_lower) / max(len(faq.get("keywords", [])), 1)
            combined = max(q_similarity, kw_score * 0.8)
            if combined > best_score:
                best_score = combined
                best_match = faq

        if best_match and best_score >= 0.60:
            return best_match["answer"], best_match["category"], best_score
        return None, None, 0.0

    def construct_expert_prompt(self, question: str, context: Optional[str] = None,
                                conversation_context: str = "", sources: List[str] = None) -> str:
        sections = []

        system = (
            "You are the UDSM Student Support Assistant. Answer based only on the official UDSM information below. "
            "Never invent policies or fees."
        )
        sections.append(system)

        if conversation_context:
            sections.append(conversation_context)

        if context:
            context_truncated = context[:2000] if len(context) > 2000 else context
            sections.append(f"Official UDSM information:\n{context_truncated}")

        sections.append(f"Student question: {question}")

        return "\n\n".join(sections)

    def check_connection(self) -> Tuple[bool, Optional[str]]:
        try:
            from urllib.parse import urlparse
            parsed = urlparse(self.api_url)
            base_url = f"{parsed.scheme}://{parsed.netloc}"

            response = requests.get(base_url, timeout=2)
            if response.status_code != 200:
                return False, f"Ollama server returned status code {response.status_code}"

            tags_url = f"{base_url}/api/tags"
            tags_response = requests.get(tags_url, timeout=2)
            if tags_response.status_code == 200:
                models_list = tags_response.json().get("models", [])
                model_names = [m.get("name") for m in models_list]
                if self.model in model_names or f"{self.model}:latest" in model_names:
                    return True, None
                short_name = self.model.split(":")[0]
                for name in model_names:
                    if name.startswith(short_name) or name.split(":")[0] == short_name:
                        return True, None
                return False, f"Model '{self.model}' is not pulled. Available: {', '.join(model_names)}"
            return True, None
        except Exception as e:
            return False, f"Failed to connect to Ollama: {str(e)}"

    def query_llm(self, prompt: str, timeout: int = 120) -> str:
        # Truncate prompt to avoid timeout on slow models
        max_prompt_chars = 4000
        if len(prompt) > max_prompt_chars:
            prompt = prompt[:max_prompt_chars] + "\n[Additional context truncated...]\n### Answer:"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.3,
                "top_p": 0.9,
                "num_predict": 1024
            }
        }
        try:
            logger.info(f"Sending request to Ollama ({self.model})")
            response = requests.post(self.api_url, json=payload, timeout=timeout)
            if response.status_code == 200:
                result = response.json()
                return result.get("response", "").strip()
            else:
                error_msg = f"Ollama returned HTTP {response.status_code}: {response.text[:200]}"
                logger.error(error_msg)
                raise LLMConnectionError(error_msg)
        except requests.exceptions.RequestException as e:
            error_msg = f"Failed to connect to Ollama at {self.api_url}: {e}"
            logger.error(error_msg)
            raise LLMConnectionError(error_msg)

    def _calculate_confidence(self, rag_used: bool, rag_score: float, sources: list,
                              faq_direct: bool, faq_score: float = 0.0) -> Tuple[str, float]:
        if faq_direct and faq_score >= 0.85:
            return "High", 0.95
        if faq_direct and faq_score >= 0.60:
            return "High", 0.88
        if rag_used and len(sources) >= 2 and rag_score >= 0.7:
            return "High", 0.85
        if rag_used and rag_score >= 0.4:
            return "Medium", 0.70
        if rag_used and rag_score >= 0.1:
            return "Medium", 0.55
        return "Low", 0.35

    def _check_web_for_updates(self, question: str) -> Optional[str]:
        time_sensitive_keywords = ["deadline", "date", "calendar", "when", "today", "current",
                                   "announcement", "closing", "opening", "application", "admission"]
        question_lower = question.lower()
        if not any(kw in question_lower for kw in time_sensitive_keywords):
            return None
        logger.info(f"Time-sensitive query detected — checking web: '{question[:50]}'")
        try:
            from urllib.parse import quote
            search_url = f"https://www.udsm.ac.tz/search?q={quote(question[:100])}"
            resp = requests.get(f"https://www.udsm.ac.tz", timeout=5)
            if resp.status_code == 200:
                return "Note: For the most current information, please check the official UDSM website (www.udsm.ac.tz) or the student portal."
        except Exception as e:
            logger.warning(f"Web check failed: {e}")
            return "Note: Please verify current dates and deadlines on the official UDSM website or student portal, as information may change."
        return None

    def _extract_steps(self, answer: str) -> list:
        action_words = r'(log\s+in|visit|navigate|click|select|submit|upload|pay|apply|check|contact|consult|go\s+to|access|register|choose|fill|download|print|send|email|provide|bring|call|attend)'
        info_prefixes = ('according to', 'based on', 'tuition fees', 'the fees', 'the cost', 'the deadline')

        sentences = re.split(r'(?<=[.!;])\s+', answer)
        action_sentences = []
        for s in sentences:
            s_clean = s.strip()
            if s_clean.lower().startswith(info_prefixes):
                continue
            if re.search(action_words, s_clean, re.IGNORECASE):
                action_sentences.append(s_clean)

        seen = set()
        steps = []
        for s in action_sentences:
            s_clean = s.rstrip('.')
            words = s_clean.split()
            s_key = ' '.join(words[:8]).lower()
            if s_key not in seen:
                steps.append(s_clean)
                seen.add(s_key)
        return steps[:5]

    def _format_structured_response(self, answer: str, sources: List[str],
                                    confidence_label: str, confidence_score: float,
                                    web_note: Optional[str] = None) -> str:
        answer = answer.strip()

        steps = self._extract_steps(answer)

        links = (
            "* Official UDSM Website: https://udsm.ac.tz\n"
            "* Student Services: https://udsm.ac.tz/directorate-students-services\n"
            "* Policies and Guidelines: https://www.udsm.ac.tz/node/1579\n"
            "* ARIS System: https://aris3.udsm.ac.tz\n"
            "* Admissions Portal: https://udsm.admission.ac.tz"
        )

        formatted = f"Answer:\n{answer}\n\n"

        if steps:
            formatted += "What you should do:\n"
            for i, s in enumerate(steps, 1):
                formatted += f"{i}. {s}.\n"
            formatted += "\n"
        else:
            formatted += "What you should do:\n1. Visit the UDSM portal at https://portal.udsm.ac.tz for detailed guidance.\n2. Contact the relevant UDSM directorate for further assistance.\n\n"

        formatted += f"Useful Links:\n{links}\n\n"

        if sources:
            formatted += "Sources:\n" + "\n".join(f"- {s}" for s in sources[:5]) + "\n\n"
        else:
            formatted += "Sources:\nNo specific documents cited.\n\n"

        if web_note:
            formatted += f"\n\n{web_note}"

        return formatted

    def _accuracy_check(self, answer: str, context: Optional[str]) -> Tuple[bool, Optional[str]]:
        if context is None:
            return True, None
        hallucination_indicators = [
            "i don't have information", "i don't know", "i am not sure",
            "i cannot provide", "unfortunately", "i'm sorry"
        ]
        answer_lower = answer.lower()
        for indicator in hallucination_indicators:
            if indicator in answer_lower:
                return True, None
        if len(answer) < 20:
            return False, "The generated response was too short to be meaningful."
        return True, None

    def generate_response(self, question: str, use_improved_prompt: bool = True) -> Dict[str, Any]:
        # 1. Check semantic cache for repeated questions
        cached = self.cache.get(question)
        if cached and cached.get("faq_direct"):
            logger.info("Returning cached FAQ answer")
            return dict(cached)

        # 2. Check FAQ direct engine (skip LLM for high-confidence FAQ matches)
        faq_answer, faq_category, faq_confidence = self.faq_direct_answer(question)
        if faq_answer and faq_confidence >= 0.85 and use_improved_prompt:
            sources = [f"UDSM FAQ - {faq_category.title()}"]
            response_data = {
                "answer": self._format_structured_response(
                    faq_answer, sources, "High", 0.95
                ),
                "rag_context_used": True,
                "category": faq_category or "General",
                "sources": sources,
                "confidence_label": "High",
                "confidence_score": 0.95,
                "faq_direct": True,
                "prompt_used": ""
            }
            self.cache.set(question, response_data)
            return response_data

        # 3. Retrieve knowledge base context
        context, category, sources, rag_score = self.retrieve_context(question)

        # 4. Get conversation memory context
        conv_context = self.memory.get_context(question)

        # 5. Check for topic repetition
        would_repeat, repeat_answer = self.memory.would_repeat(question)
        if would_repeat and repeat_answer:
            logger.info("Detected repeated question — using previous answer")

        # 6. Build prompt
        if use_improved_prompt:
            if faq_answer and faq_confidence >= 0.60:
                context = context or ""
                context += f"\n\n[FAQ DIRECT MATCH - {faq_category}]\nQ: {faq_answer[:200]}"
                category = category or faq_category
                if "FAQ" not in (sources or []):
                    sources = sources or []
                    sources.append(f"UDSM FAQ - {faq_category.title()}")

            prompt = self.construct_expert_prompt(
                question=question,
                context=context,
                conversation_context=conv_context,
                sources=sources
            )
        else:
            prompt = question

        # 7. Query LLM
        answer = self.query_llm(prompt)

        # 8. Accuracy check
        is_accurate, accuracy_note = self._accuracy_check(answer, context)

        # 9. Calculate confidence
        conf_label, conf_score = self._calculate_confidence(
            rag_used=context is not None,
            rag_score=rag_score,
            sources=sources or [],
            faq_direct=faq_answer is not None and faq_confidence >= 0.60,
            faq_score=faq_confidence
        )

        if not is_accurate and accuracy_note:
            answer += f"\n\n*Note: {accuracy_note}*"

        # 10. Check web for time-sensitive info
        web_note = self._check_web_for_updates(question)

        # 11. Format structured response
        formatted_answer = self._format_structured_response(
            answer, sources or [], conf_label, conf_score, web_note
        ) if use_improved_prompt else answer

        # 12. Store in memory
        self.memory.add(question, formatted_answer)

        response_data = {
            "answer": formatted_answer,
            "rag_context_used": context is not None,
            "category": category or (faq_category if faq_answer else "General"),
            "sources": sources or [],
            "confidence_label": conf_label,
            "confidence_score": conf_score,
            "faq_direct": faq_answer is not None and faq_confidence >= 0.60,
            "prompt_used": prompt if not use_improved_prompt else prompt
        }

        # 13. Update cache
        self.cache.set(question, response_data)

        return response_data
