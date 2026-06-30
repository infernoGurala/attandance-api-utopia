import os
from typing import Optional, Dict
from fastapi import FastAPI, HTTPException, Body
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import uvicorn

from scraper import scrape_with_cookies, scrape_with_browser_login, PLAYWRIGHT_AVAILABLE

app = FastAPI(
    title="College Attendance API",
    description="API server to scrape student attendance from info.aec.edu.in portal"
)

class AttendanceRequest(BaseModel):
    roll_number: str = Field(..., description="Student Roll Number")
    password: Optional[str] = Field(None, description="Portal Password (required if cookies not provided/expired)")
    college: str = Field("aus", description="College key: 'aus' or 'acet'")
    from_date: Optional[str] = Field("", description="Start date (YYYY-MM-DD) for range mode")
    to_date: Optional[str] = Field("", description="End date (YYYY-MM-DD) for range mode")
    mode: Optional[str] = Field("period", description="Mode: 'period' (range) or 'tillNow'")
    cookies: Optional[Dict[str, str]] = Field(None, description="Pre-existing session cookies to bypass login")

@app.post("/api/attendance")
async def get_attendance(req: AttendanceRequest):
    college = req.college.lower().strip()
    if college not in ["aus", "acet"]:
        raise HTTPException(status_code=400, detail="Invalid college name. Must be 'aus' or 'acet'.")

    # Method 1: Direct scrape if cookies are provided
    if req.cookies:
        try:
            data = await scrape_with_cookies(
                roll_number=req.roll_number,
                college=college,
                cookies=req.cookies,
                from_date=req.from_date,
                to_date=req.to_date,
                mode=req.mode
            )
            return {
                "success": True,
                "method": "cookies",
                "cookies": req.cookies,
                "data": data
            }
        except Exception as e:
            # If cookies fail and we have a password, fall back to browser login
            if not req.password:
                raise HTTPException(
                    status_code=401,
                    detail=f"Cookie-based scraping failed: {str(e)}. Please provide password to re-authenticate."
                )
            # Otherwise we fall through to try browser login

    # Method 2: Headless browser login
    if not req.password:
        raise HTTPException(status_code=400, detail="Password or valid active cookies are required.")
        
    if not PLAYWRIGHT_AVAILABLE:
        raise HTTPException(
            status_code=500, 
            detail="Headless browser login is unavailable (Playwright not installed). Please provide active cookies."
        )

    try:
        data = await scrape_with_browser_login(
            roll_number=req.roll_number,
            password=req.password,
            college=college,
            from_date=req.from_date,
            to_date=req.to_date,
            mode=req.mode
        )
        obtained_cookies = data.pop("cookies", {})
        return {
            "success": True,
            "method": "browser",
            "cookies": obtained_cookies,
            "data": data
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Scraping failed: {str(e)}")

# Set up static directory
static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
if not os.path.exists(static_dir):
    os.makedirs(static_dir)

@app.get("/")
async def read_index():
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return HTMLResponse("<h1>WebUI static/index.html is not created yet!</h1>")

# Mount static folder
app.mount("/static", StaticFiles(directory=static_dir), name="static")

if __name__ == "__main__":
    # Hugging Face Spaces port defaults to 7860, local uvicorn defaults to 8000
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
