import streamlit as st

st.set_page_config(
    page_title="UDSM Student Support AI Portal",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
    header[data-testid="stHeader"] { display: none !important; }
    section[data-testid="stSidebar"] { display: none !important; }
    .stAppDeployButton, .stActionButton, [data-testid="stToolbar"] { display: none !important; }
    .main .block-container { padding: 0 !important; max-width: 100% !important; }
    #root > div:first-child > div:first-child { padding: 0 !important; }
    iframe {
        border: none;
        width: 100vw;
        height: 100vh;
        position: fixed;
        top: 0;
        left: 0;
        min-width: 320px;
    }
    @media (max-width: 768px) {
        .main .block-container { padding: 0 !important; }
        iframe { height: 100dvh; }
    }
</style>
""", unsafe_allow_html=True)

st.markdown(
    '<iframe src="http://localhost:8000/" title="UDSM Portal"></iframe>',
    unsafe_allow_html=True
)
