from pydantic import BaseModel


class URLPayload(BaseModel):
    urls: list[str]
