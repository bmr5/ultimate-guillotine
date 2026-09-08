import secrets

from fastapi import FastAPI, HTTPException, Request

from ultimate_guillotine.messages.bluebubbles import parse_webhook


def create_app(processor, heartbeats, webhook_password: str) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/healthz")
    def healthz() -> dict:
        return {"ok": True}

    @app.post("/bluebubbles-webhook")
    async def webhook(request: Request) -> dict:
        supplied = request.query_params.get("password") or request.headers.get("x-password") or ""
        if not secrets.compare_digest(supplied, webhook_password):
            raise HTTPException(status_code=401)
        payload = await request.json()
        heartbeats.beat("listener")
        msg = parse_webhook(payload)
        if msg is None:
            return {"outcome": "ignored_event"}
        return {"outcome": processor.process(msg, msg.guid)}

    return app
