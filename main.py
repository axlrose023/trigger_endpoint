from fastapi import FastAPI, Request
import asyncio

from scrapper import Scrapper

app = FastAPI()


@app.post("/scrape")
async def scrape(request: Request):
    data = await request.json()
    account = data.get("account")
    print(account, 'status active')
    return {"account": account}
    # scrapper = Scrapper()
    # recent_posts = await asyncio.to_thread(scrapper.get_new_posts, account)
    # return {"account": account, "recent_posts": recent_posts}
