"""번역 엔진 내부 구현.

- graph_orchestrator : LangGraph 상태머신(번역→검수→복구→주석)
- literary_package   : 순수 스텝/자료구조(idiom 감지, RAG 패킷, rationale, 결과 dataclass)

최상위 `translation_pipeline.py`가 이 엔진을 조립해 실행한다.
"""
