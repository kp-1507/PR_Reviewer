from fastapi import FastAPI, Request

app = FastAPI()


@app.post("/webhook/github")
async def github_webhook(request: Request):
    payload = await request.json()

    print("Webhook received!")
    print("Action:", payload.get("action"))
    print("PR Number:", payload.get("number"))

    return {"status": "received"}