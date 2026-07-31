from app.ai_tools.router import router
from app.auth import create_token
from app.config import get_settings
from app.database import Base, get_db
from app.models import User
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


def build_client():
    engine=create_engine("sqlite+pysqlite:///:memory:",connect_args={"check_same_thread":False},poolclass=StaticPool)
    Base.metadata.create_all(engine,tables=[User.__table__]); db=Session(engine)
    user=User(username="tools",password_hash="x",status="active",role="user"); db.add(user); db.commit(); db.refresh(user)
    app=FastAPI(); app.include_router(router)
    def session_override(): yield db
    app.dependency_overrides[get_db]=session_override
    return TestClient(app),db,user


def test_debug_api_auth_list_detail_execute_batch_and_schema():
    client,db,user=build_client()
    try:
        assert client.get("/api/ai-tools/v1/tools").status_code==401
        headers={"Authorization":f"Bearer {create_token(user.id)}"}
        listing=client.get("/api/ai-tools/v1/tools?domain=news",headers=headers)
        assert listing.status_code==200 and listing.json()["count"]==4
        assert "input_schema" not in listing.json()["tools"][0]
        detail=client.get("/api/ai-tools/v1/tools/get_latest_news",headers=headers)
        assert detail.status_code==200 and detail.json()["read_only"] is True
        schema=client.get("/api/ai-tools/v1/openai-schema?tools=get_latest_news",headers=headers)
        assert schema.status_code==200 and schema.json()["tools"][0]["function"]["name"]=="get_latest_news"
        execution=client.post("/api/ai-tools/v1/execute",headers=headers,json={"tool":"list_research_capabilities","arguments":{"result_mode":"compact"}})
        assert execution.status_code==200 and execution.json()["status"]=="success"
        injected=client.post("/api/ai-tools/v1/execute",headers=headers,json={"tool":"list_research_capabilities","arguments":{"user_id":user.id}})
        assert injected.json()["error"]["code"]=="TOOL_ARGUMENTS_INVALID"
        batch=client.post("/api/ai-tools/v1/execute-batch",headers=headers,json={"calls":[{"tool":"list_research_capabilities","arguments":{}},{"tool":"unknown","arguments":{}}]})
        assert [row["status"] for row in batch.json()]==["success","error"]
        too_many=client.post("/api/ai-tools/v1/execute-batch",headers=headers,json={"calls":[{"tool":"list_research_capabilities"} for _ in range(9)]})
        assert too_many.status_code==422
        assert any(path.startswith("/api/ai-tools/v1") for path in client.app.openapi()["paths"])
    finally: db.close()


def test_debug_api_disabled_returns_not_found():
    client,db,user=build_client(); settings=get_settings(); previous=settings.ai_tools_debug_api_enabled
    try:
        settings.ai_tools_debug_api_enabled=False
        response=client.get("/api/ai-tools/v1/tools",headers={"Authorization":f"Bearer {create_token(user.id)}"})
        assert response.status_code==404
    finally:
        settings.ai_tools_debug_api_enabled=previous; db.close()

