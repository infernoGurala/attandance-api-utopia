import re
import base64
import asyncio
import datetime
from typing import Dict, Optional, Any, Tuple
from bs4 import BeautifulSoup
import httpx
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding

# Playwright/Patchright imports for headless browser option
try:
    from patchright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

PORTAL_HOST = "info.aec.edu.in"
AES_SECRET = "8701661282118308"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

def encrypt_password(password: str) -> str:
    """Encrypts password using AES-128-CBC with PKCS7 padding as expected by the portal."""
    key = AES_SECRET.encode('utf-8')
    iv = AES_SECRET.encode('utf-8')
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    encryptor = cipher.encryptor()
    
    padder = padding.PKCS7(128).padder()
    padded_data = padder.update(password.encode('utf-8')) + padder.finalize()
    
    encrypted_data = encryptor.update(padded_data) + encryptor.finalize()
    return base64.b64encode(encrypted_data).decode('utf-8')

def parse_attendance_html(html_content: str) -> Optional[Dict[str, Any]]:
    """Robust parser for both ACET and AUS attendance HTML tables."""
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Try finding the report table
    table = soup.find('table', id='tblReport')
    if not table:
        profile_div = soup.find('div', id='divProfile_Present')
        if profile_div:
            table = profile_div.find('table')
        if not table:
            # Fallback to any table
            table = soup.find('table')
            
    if not table:
        return None
        
    subjects = []
    overall = {
        'overallPercentage': 0.0,
        'totalClasses': 0,
        'totalAttended': 0,
        'studentName': None,
        'hasReport': False
    }
    
    # Extract student name if available in the text
    text = soup.get_text(separator=' ')
    name_match = re.search(
        r'Name\s*:\s*([^:]+?)(?=\s*(?:RollNo|Roll\s*No|Branch|Course|Semester|College|$))', 
        text, 
        re.IGNORECASE
    )
    if name_match:
        overall['studentName'] = name_match.group(1).strip()
        
    rows = table.find_all('tr')
    
    subject_idx = None
    held_idx = None
    attend_idx = None
    percent_idx = None
    
    for row in rows:
        # Check if header row
        th_cells = row.find_all('th')
        if th_cells:
            for idx, th in enumerate(th_cells):
                txt = th.get_text().strip().lower()
                if any(kw in txt for kw in ['subject', 'course', 'paper', 'subject name']):
                    subject_idx = idx
                elif 'held' in txt:
                    held_idx = idx
                elif 'attend' in txt and 'attendance' not in txt:
                    attend_idx = idx
                elif '%' in txt or 'percent' in txt:
                    percent_idx = idx
            continue
            
        td_cells = row.find_all('td')
        if not td_cells:
            continue
            
        cells_text = [td.get_text().strip() for td in td_cells]
        if len([c for c in cells_text if c]) < 2:
            continue
            
        # Fallback heuristic if headers not identified
        if subject_idx is None or held_idx is None or attend_idx is None:
            sub_name = None
            held = None
            attend = None
            pct = 0.0
            
            for idx, c in enumerate(cells_text):
                c_lower = c.lower().strip()
                if c and (c_lower == 'total' or any(ch.isalpha() for ch in c_lower)):
                    if not any(kw in c_lower for kw in ['percent', 'attended', 'held', 'percentage']):
                        sub_name = c
                        nums = []
                        for cell_val in cells_text[idx+1:]:
                            digit_match = re.search(r'\d+', cell_val)
                            if digit_match:
                                nums.append(int(digit_match.group()))
                            if len(nums) >= 2:
                                break
                        if len(nums) >= 2:
                            held, attend = nums[0], nums[1]
                        break
        else:
            sub_name = cells_text[subject_idx] if subject_idx < len(cells_text) else None
            held_str = cells_text[held_idx] if held_idx < len(cells_text) else ''
            attend_str = cells_text[attend_idx] if attend_idx < len(cells_text) else ''
            
            held = int(re.search(r'\d+', held_str).group()) if re.search(r'\d+', held_str) else None
            attend = int(re.search(r'\d+', attend_str).group()) if re.search(r'\d+', attend_str) else None
            
        if not sub_name or held is None or attend is None:
            continue
            
        pct = (attend / held * 100) if held > 0 else 0.0
        if percent_idx is not None and percent_idx < len(cells_text):
            pct_str = cells_text[percent_idx].strip()
            pct_match = re.search(r'\d+(?:\.\d+)?', pct_str)
            if pct_match:
                pct = float(pct_match.group())
                
        sub_name_clean = sub_name.strip()
        if sub_name_clean.lower() == 'total':
            overall['hasReport'] = True
            overall['totalClasses'] = held
            overall['totalAttended'] = attend
            overall['overallPercentage'] = round(pct, 1)
        else:
            if any(kw in sub_name_clean.lower() for kw in ['subject', 'sl.no', 'sr.no', 'sl no', 'sr no']):
                continue
            subjects.append({
                'subject': sub_name_clean,
                'totalClasses': held,
                'attendedClasses': attend,
                'percentage': round(pct, 1)
            })
            
    if not overall['hasReport'] and subjects:
        total_held = sum(s['totalClasses'] for s in subjects)
        total_attended = sum(s['attendedClasses'] for s in subjects)
        overall['totalClasses'] = total_held
        overall['totalAttended'] = total_attended
        overall['overallPercentage'] = round(total_attended / total_held * 100, 1) if total_held > 0 else 0.0
        
    overall['subjects'] = subjects
    return overall

async def scrape_with_cookies(
    roll_number: str,
    college: str,
    cookies: Dict[str, str],
    from_date: str = "",
    to_date: str = "",
    mode: str = "period",
    user_agent: Optional[str] = None
) -> Dict[str, Any]:
    """Direct HTTP scraping using valid pre-existing cookies (bypasses Cloudflare login)."""
    prefix = f"/{college}"
    ua = user_agent or USER_AGENT
    headers = {
        "User-Agent": ua,
        "Accept-Language": "en-IN,en;q=0.9",
        "Cookie": "; ".join([f"{k}={v}" for k, v in cookies.items()]),
    }
    
    async with httpx.AsyncClient(timeout=20.0) as client:
        # Step 1: Request StudentMaster to populate session context
        master_url = f"https://{PORTAL_HOST}{prefix}/StudentMaster.aspx"
        await client.get(master_url, headers=headers, follow_redirects=True)
        
        if college == "aus":
            # For AUS: Fetch Profile page and invoke ShowStudentProfileNew API
            profile_url = f"https://{PORTAL_HOST}{prefix}/Academics/StudentProfile.aspx?scrid=17"
            profile_res = await client.get(profile_url, headers=headers, follow_redirects=True)
            
            # Find the actual roll number parameter
            roll_match = re.search(
                r'id="ctl00_CapPlaceHolder_txtRollNo"[^>]*value="([^"]+)"',
                profile_res.text
            )
            roll_no_val = roll_match.group(1) if roll_match else roll_number
            
            # AuthToken might be stored in cookies
            auth_token = cookies.get("AuthToken", cookies.get("authtoken", ""))
            
            api_url = f"https://{PORTAL_HOST}{prefix}/Academics/studentprofile.aspx/ShowStudentProfileNew"
            api_headers = {
                **headers,
                "Content-Type": "application/json; charset=UTF-8",
                "Origin": f"https://{PORTAL_HOST}",
                "Referer": profile_url,
                "X-Requested-With": "XMLHttpRequest",
                "X-Auth-Token": auth_token,
                "Accept": "application/json, text/javascript, */*",
            }
            
            payload = {
                "RollNo": roll_no_val,
                "isImageDisplay": False
            }
            
            api_res = await client.post(api_url, json=payload, headers=api_headers)
            if api_res.status_code != 200:
                raise Exception(f"Failed to fetch profile API. Status: {api_res.status_code}")
                
            try:
                html_data = api_res.json().get('d', '')
            except Exception:
                html_data = api_res.text
                
            parsed = parse_attendance_html(html_data)
            if not parsed:
                raise Exception("Attendance data table could not be parsed from profile page.")
            return parsed
            
        else:
            # For ACET: Fetch Attendance page and invoke ShowAttendance API
            att_url = f"https://{PORTAL_HOST}{prefix}/Academics/StudentAttendance.aspx?scrid=3&showtype=SA"
            att_res = await client.get(att_url, headers=headers, follow_redirects=True)
            
            # Extract web method token
            token = ""
            token_patterns = [
                r"var\s+_tkn\s*=\s*'([^']+)'",
                r"var\s+_tkn\s*=\s*\"([^\"]+)\"",
                r"['\"]_tkn['\"]\s*:\s*'([^']+)'",
                r"['\"]_tkn['\"]\s*:\s*\"([^\"]+)\"",
                r"var\s+token\s*=\s*'([^']+)'",
                r"var\s+token\s*=\s*\"([^\"]+)\"",
                r"var\s+authToken\s*=\s*\"([^\"]+)\"",
                r"var\s+authToken\s*=\s*'([^']+)'"
            ]
            
            for pat in token_patterns:
                match = re.search(pat, att_res.text, re.IGNORECASE)
                if match:
                    token = match.group(1)
                    break
                    
            # Parse dates
            formatted_from = ""
            formatted_to = ""
            if mode == "period" and from_date and to_date:
                # Expecting YYYY-MM-DD from API inputs, convert to DD-MM-YYYY
                try:
                    fd = datetime.datetime.strptime(from_date, "%Y-%m-%d")
                    td = datetime.datetime.strptime(to_date, "%Y-%m-%d")
                    formatted_from = fd.strftime("%d-%m-%Y")
                    formatted_to = td.strftime("%d-%m-%Y")
                except ValueError:
                    formatted_from = from_date
                    formatted_to = to_date
            
            # Fetch script AjaxMethods.js to simulate behavior
            ajax_url = f"https://{PORTAL_HOST}{prefix}/JSFiles/AjaxMethods.js"
            await client.get(ajax_url, headers=headers)
            
            api_url = f"https://{PORTAL_HOST}{prefix}/Academics/studentattendance.aspx/ShowAttendance"
            api_headers = {
                **headers,
                "Content-Type": "application/json; charset=UTF-8",
                "Origin": f"https://{PORTAL_HOST}",
                "Referer": att_url,
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json, text/javascript, */*",
            }
            if token:
                api_headers["x-auth-token"] = token
                
            payload = {
                "fromDate": formatted_from,
                "toDate": formatted_to,
                "excludeothersubjects": False
            }
            
            api_res = await client.post(api_url, json=payload, headers=api_headers)
            if api_res.status_code != 200:
                raise Exception(f"Failed to fetch attendance API. Status: {api_res.status_code}")
                
            try:
                html_data = api_res.json().get('d', '')
            except Exception:
                html_data = api_res.text
                
            parsed = parse_attendance_html(html_data)
            if not parsed:
                raise Exception("Attendance data table could not be parsed from attendance page.")
            return parsed

async def scrape_with_browser_login(
    roll_number: str,
    password: str,
    college: str,
    from_date: str = "",
    to_date: str = "",
    mode: str = "period"
) -> Dict[str, Any]:
    """Headful browser scraping using Patchright (under xvfb) to solve Turnstile and log in."""
    import os
    # Force Chromium to use X11/Xvfb instead of escaping to Wayland/host display
    for var in ["WAYLAND_DISPLAY", "GNOME_SETUP_DISPLAY"]:
        if var in os.environ:
            del os.environ[var]

    if not PLAYWRIGHT_AVAILABLE:
        raise Exception("Patchright/Playwright library is not installed on this system.")
        
    prefix = f"/{college}"
    login_url = f"https://{PORTAL_HOST}{prefix}/default.aspx"
    encrypted_pwd = encrypt_password(password)
    
    async with async_playwright() as p:
        # Launch browser headfully (requires xvfb-run on headless servers)
        browser = await p.chromium.launch(
            headless=False,
            args=["--no-sandbox", "--disable-setuid-sandbox"]
        )
        
        context = await browser.new_context(
            viewport={"width": 360, "height": 800}
        )
        
        page = await context.new_page()
        
        # Navigate to login page
        await page.goto(login_url, wait_until="domcontentloaded")
        
        # Wait for form elements
        is_form_ready = False
        for _ in range(30):
            has_user = await page.query_selector("#txtUserId") or await page.query_selector("#txtId2")
            if has_user:
                is_form_ready = True
                break
            await asyncio.sleep(0.3)
            
        if not is_form_ready:
            await browser.close()
            raise Exception("Login form elements not loaded or blocked by Cloudflare.")
            
        # Cloudflare Turnstile Solve (Coordinate click inside iframe)
        await asyncio.sleep(6)
        
        cf_frame = None
        for frame in page.frames:
            if "challenges.cloudflare.com" in frame.url:
                cf_frame = frame
                break
                
        if cf_frame:
            element = await cf_frame.frame_element()
            if element:
                box = await element.bounding_box()
                if box:
                    click_x = box['x'] + 35
                    click_y = box['y'] + (box['height'] / 2)
                    
                    # Move mouse in human-like steps and click
                    await page.mouse.move(click_x, click_y, steps=15)
                    await asyncio.sleep(0.2)
                    await page.mouse.click(click_x, click_y)
                    
                    # Wait up to 10 seconds for the Turnstile response token
                    for _ in range(20):
                        token = await page.evaluate(
                            "var el = document.querySelector('[name=\"cf-turnstile-response\"]'); el ? el.value : '';"
                        )
                        if token:
                            break
                        await asyncio.sleep(0.5)
                
        # Fill in credentials using evaluation or playwright fill
        js_fill = f"""
            (function() {{
                var u1 = document.querySelector('#txtId1');
                var u2 = document.querySelector('#txtId2') || document.querySelector('#txtUserId');
                var u3 = document.querySelector('#txtId3');
                if (u1) u1.value = '{roll_number.strip()}';
                if (u2) u2.value = '{roll_number.strip()}';
                if (u3) u3.value = '{roll_number.strip()}';

                var p1 = document.querySelector('#txtPwd1');
                var p2 = document.querySelector('#txtPwd2') || document.querySelector('#txtPassword');
                var p3 = document.querySelector('#txtPwd3');
                if (p1) p1.value = '{encrypted_pwd}';
                if (p2) p2.value = '{encrypted_pwd}';
                if (p3) p3.value = '{encrypted_pwd}';

                var h1 = document.querySelector('#hdnpwd1') || document.querySelector('#hdnpwd');
                var h2 = document.querySelector('#hdnpwd2');
                var h3 = document.querySelector('#hdnpwd3');
                if (h1) h1.value = '{encrypted_pwd}';
                if (h2) h2.value = '{encrypted_pwd}';
                if (h3) h3.value = '{encrypted_pwd}';

                var rbt = document.querySelector('#rbtStudent') || document.querySelector('#rbtStudent2');
                if (rbt) rbt.checked = true;
            }})();
        """
        await page.evaluate(js_fill)
        
        # Click login button
        login_btn = await page.query_selector("#btnLogin") or await page.query_selector("#imgBtn2")
        if login_btn:
            await login_btn.click()
        else:
            await page.evaluate("document.querySelector('form').submit()")
            
        # Wait for navigation to StudentMaster
        success = False
        for _ in range(30):
            current_url = page.url
            if "StudentMaster.aspx" in current_url:
                success = True
                break
            await asyncio.sleep(0.3)
            
        if not success:
            await browser.close()
            raise Exception("Invalid credentials or login failed to redirect to StudentMaster.")
            
        # Get cookies and native browser user agent
        pw_cookies = await context.cookies()
        cookie_dict = {c['name']: c['value'] for c in pw_cookies}
        browser_ua = await page.evaluate("navigator.userAgent")
        
        await browser.close()
        
        # Now run the fast HTTP scraper with the acquired cookies
        attendance_data = await scrape_with_cookies(
            roll_number=roll_number,
            college=college,
            cookies=cookie_dict,
            from_date=from_date,
            to_date=to_date,
            mode=mode,
            user_agent=browser_ua
        )
        
        return {
            **attendance_data,
            "cookies": cookie_dict
        }
