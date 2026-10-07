import uvicorn

from app.partner.api import app
from app.settings import settings

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=settings.partner_port, log_level="info")
