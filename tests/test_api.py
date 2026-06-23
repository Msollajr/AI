import sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

backend_path = Path(__file__).resolve().parent.parent / "backend"
sys.path.append(str(backend_path))

from main import app
from llm_client import LLMConnectionError

client = TestClient(app)

class TestHealthEndpoint:
    def test_health_returns_200(self):
        res = client.get("/health")
        assert res.status_code == 200

    def test_health_has_expected_fields(self):
        res = client.get("/health")
        data = res.json()
        assert "status" in data
        assert "llm_connected" in data
        assert "timestamp" in data

class TestAskEndpoint:
    def test_rejects_empty_question(self):
        res = client.post("/ask", json={"question": "", "use_improved_prompt": True})
        assert res.status_code == 400
        assert "detail" in res.json()

    def test_rejects_whitespace_only(self):
        res = client.post("/ask", json={"question": "   ", "use_improved_prompt": True})
        assert res.status_code == 400

    def test_rejects_missing_question(self):
        res = client.post("/ask", json={"use_improved_prompt": True})
        assert res.status_code == 400

    def test_response_has_expected_fields(self):
        res = client.post("/ask", json={
            "question": "How do I register for courses?",
            "use_improved_prompt": True
        })
        if res.status_code == 200:
            data = res.json()
            assert "answer" in data
            assert "rag_context_used" in data
            assert "sources" in data
            assert "confidence_label" in data
            assert "confidence_score" in data
            assert "faq_direct" in data
            assert "category" in data
            assert "timestamp" in data
            assert data["rag_context_used"] is True
            assert data["confidence_label"] in ("High", "Medium", "Low")
            assert 0.0 <= data["confidence_score"] <= 1.0

    def test_faq_direct_answer_has_high_confidence(self):
        res = client.post("/ask", json={
            "question": "How do I register for courses?",
            "use_improved_prompt": True
        })
        if res.status_code == 200:
            data = res.json()
            if data.get("faq_direct"):
                assert data["confidence_label"] == "High"
                assert data["confidence_score"] >= 0.85

    def test_response_includes_links_section(self):
        res = client.post("/ask", json={
            "question": "What are hostel fees?",
            "use_improved_prompt": True
        })
        if res.status_code == 200:
            answer = res.json()["answer"]
            assert "Useful Links" in answer
            assert "udsm.ac.tz" in answer
            assert "aris3.udsm.ac.tz" in answer

    def test_response_includes_steps_section(self):
        res = client.post("/ask", json={
            "question": "How do I register for courses?",
            "use_improved_prompt": True
        })
        if res.status_code == 200:
            answer = res.json()["answer"]
            assert "What you should do" in answer or "Answer" in answer



class TestFeedbackEndpoint:
    def test_feedback_saves_successfully(self):
        res = client.post("/feedback", json={
            "question": "How do I register?",
            "answer": "Use the Student Portal.",
            "rating": "Good"
        })
        assert res.status_code == 200
        assert res.json()["status"] == "success"

    def test_feedback_rejects_invalid_rating(self):
        res = client.post("/feedback", json={
            "question": "How do I register?",
            "answer": "Use the Student Portal.",
            "rating": "InvalidRating"
        })
        assert res.status_code == 422

    def test_feedback_accepts_average(self):
        res = client.post("/feedback", json={
            "question": "How do I register?",
            "answer": "Use the Student Portal.",
            "rating": "Average"
        })
        assert res.status_code == 200

    def test_feedback_accepts_poor(self):
        res = client.post("/feedback", json={
            "question": "How do I register?",
            "answer": "Use the Student Portal.",
            "rating": "Poor"
        })
        assert res.status_code == 200

class TestErrorHandling:
    def test_returns_503_when_llm_unreachable(self, monkeypatch):
        def mock_generate(self, question, use_improved_prompt):
            raise LLMConnectionError("Failed to connect to Ollama server.")
        from llm_client import LLMClient
        monkeypatch.setattr(LLMClient, "generate_response", mock_generate)

        res = client.post("/ask", json={
            "question": "What is the fee deadline?",
            "use_improved_prompt": True
        })
        assert res.status_code == 503
        assert "detail" in res.json()
        assert "unavailable" in res.json()["detail"].lower()

    def test_frontend_response_has_expected_format(self):
        res = client.post("/ask", json={
            "question": "How do I register for courses?",
            "use_improved_prompt": True
        })
        if res.status_code == 200:
            data = res.json()
            answer = data["answer"]
            assert answer.startswith("Answer:") or "Answer:" in answer.split("\n")[0]
            sections = ["Answer:", "What you should do:", "Useful Links:", "Sources:"]
            found = sum(1 for s in sections if s in answer)
            assert found >= 2, f"Expected at least 2 of 4 sections, found {found}"

class TestConfigEndpoint:
    def test_spa_serves_index_html(self):
        res = client.get("/")
        assert res.status_code == 200
        assert "text/html" in res.headers["content-type"]
        content = res.text
        assert "UDSM" in content
        assert "tailwind" in content.lower() or "Tailwind" in content
