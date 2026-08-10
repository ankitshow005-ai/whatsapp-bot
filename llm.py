"""llm.py - Multi-provider router"""
import logging
import re
from functools import lru_cache
from config import (
    LLM_PRIORITY,
    GEMINI_API_KEY,GEMINI_MODEL,
    GROQ_API_KEY,GROQ_MODEL,
    OPENAI_API_KEY,OPENAI_MODEL,
    QWEN_API_KEY,QWEN_MODEL,QWEN_API_BASE,
    MISTRAL_API_KEY,MISTRAL_MODEL,
)
logger=logging.getLogger(__name__)
def _provider_has_key(p):
    return {"gemini":bool(GEMINI_API_KEY),"groq":bool(GROQ_API_KEY),"openai":bool(OPENAI_API_KEY),"qwen":bool(QWEN_API_KEY),"mistral":bool(MISTRAL_API_KEY)}.get(p,False)
@lru_cache(maxsize=4)
def get_client(p):
    p=p.lower()
    if p=="gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(model=GEMINI_MODEL,google_api_key=GEMINI_API_KEY,temperature=0.3,timeout=10,max_retries=1)
    if p=="groq":
        from langchain_groq import ChatGroq
        return ChatGroq(model=GROQ_MODEL,groq_api_key=GROQ_API_KEY,temperature=0.3,timeout=8,max_retries=1)
    if p=="openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=OPENAI_MODEL,api_key=OPENAI_API_KEY,temperature=0.3,timeout=8,max_retries=1)
    if p=="qwen":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=QWEN_MODEL,api_key=QWEN_API_KEY,base_url=QWEN_API_BASE,temperature=0.3,timeout=10,max_retries=1)
    if p=="mistral":
        from langchain_mistralai import ChatMistralAI
        return ChatMistralAI(model=MISTRAL_MODEL,api_key=MISTRAL_API_KEY,temperature=0.3,timeout=10,max_retries=1)
    raise ValueError(p)
def _should_fallback(e):
    m=str(e).lower()
    return any(x in m for x in ["429","quota","rate limit","resource exhausted","timeout","timed out","deadline","connection","500","502","503","service unavailable"])
def ask_llm(prompt:str)->str:
    last=None
    for p in LLM_PRIORITY:
        p=p.lower()
        if not _provider_has_key(p):
            logger.info("Skipping %s (no API key)",p);continue
        try:
            logger.info("Trying %s",p)
            r=get_client(p).invoke(prompt)
            logger.info("%s succeeded",p)
            return r.content.strip()
        except Exception as e:
            last=e
            logger.warning("%s failed: %s",p,e)
            if _should_fallback(e):
                continue
            raise
    raise RuntimeError(f"No LLM provider available. Last error: {last}")