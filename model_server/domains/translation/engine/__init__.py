"""v3 번역 엔진 내부 구현.

- graph_orchestrator : LangGraph 상태머신(번역→검수→복구→주석 노드/엣지/라우팅)
- literary_package   : 엔진이 쓰는 순수 스텝/자료구조(idiom 감지, RAG 패킷, rationale, 결과 dataclass)

최상위 `translation_pipeline.py`(오케스트레이터)가 이 엔진을 조립해 실행한다.
"""
