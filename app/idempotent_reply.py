"""Return an existing idempotent result using a representation the current client accepts."""
import gzip
import io
import math
from starlette.responses import JSONResponse


def quality(header,coding):
    preferences={}
    for item in header.split(","):
        name,*options=item.strip().lower().split(";")
        if not name:continue
        q=1.0
        for option in options:
            key,_,value=option.strip().partition("=")
            if key=="q":
                try:q=float(value)
                except ValueError:q=0
        preferences[name]=q if math.isfinite(q) and 0<=q<=1 else 0
    if coding=="identity":
        return preferences.get("identity",0 if preferences.get("*")==0 else 1)
    return preferences.get(coding,preferences.get("*",0))


async def reply(cached,headers,scope,receive,send):
    stored={k.lower():v for k,v in cached["response_headers"]}
    source=stored.get("content-encoding","identity").lower()
    accepted=headers.get("accept-encoding","")
    if quality(accepted,source)>0:
        target=source
    elif source=="gzip" and quality(accepted,"identity")>0:
        target="identity"
    elif source=="identity" and quality(accepted,"gzip")>0:
        target="gzip"
    else:
        await JSONResponse({"detail":"Cached response cannot be delivered with the requested encoding"},status_code=406)(scope,receive,send)
        return
    omit={"content-length","x-request-id","x-idempotent-replay","content-encoding","vary"}
    if source!=target:omit.update({"etag","content-md5","content-digest"})
    response_headers=[(k.encode("latin-1"),v.encode("latin-1")) for k,v in cached["response_headers"] if k.lower() not in omit]
    vary=[part.strip() for part in stored.get("vary","").split(",") if part.strip()]
    if "*" not in vary and "accept-encoding" not in {v.lower() for v in vary}:vary.append("Accept-Encoding")
    response_headers.extend([(b"vary",", ".join(vary).encode()),(b"x-idempotent-replay",b"true")])
    if target!="identity":response_headers.append((b"content-encoding",target.encode()))
    raw=bytes(cached["response_body"])
    await send({"type":"http.response.start","status":cached["status_code"],"headers":response_headers})
    if source=="gzip" and target=="identity":
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as old:
            while block:=old.read(65536):
                await send({"type":"http.response.body","body":block,"more_body":True})
        raw=b""
    elif source=="identity" and target=="gzip":
        raw=gzip.compress(raw)
    await send({"type":"http.response.body","body":raw})
