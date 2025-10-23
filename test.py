from fastapi import FastAPI, HTTPException
from contextlib import asynccontextmanager
from playwright.async_api import async_playwright, Page
import uvicorn
from llmGoogle import llm
import time
import uuid
import json
import logging
from typing import Dict, Optional, Any, List
from datetime import datetime, timedelta
import asyncio
from dataclasses import dataclass, field
from pydantic import BaseModel, Field, validator
from enum import Enum

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/browser_automation.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Configuration
@dataclass
class Config:
    MAX_RETRIES: int = 5
    SESSION_TIMEOUT_MINUTES: int = 30
    PAGE_WAIT_TIMEOUT: int = 4000
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    HEADLESS: bool = False
    BROWSER_TIMEOUT: int = 15000
    USE_JAVASCRIPT_EXECUTION: bool = True  # Use JS execution instead of direct Playwright commands

config = Config()


# Pydantic Models for API
class ModeEnum(str, Enum):
    """Available automation modes."""
    INTERACT = "interact"
    SCRAPE = "scrape"
    TEST = "test"


class StartSessionRequest(BaseModel):
    """Request model for starting a new session."""
    mode: ModeEnum = Field(default=ModeEnum.INTERACT, description="Automation mode to use")
    
    class Config:
        use_enum_values = True


class StartSessionResponse(BaseModel):
    """Response model for session creation."""
    session_id: str = Field(..., description="Unique session identifier")
    mode: str = Field(..., description="Automation mode being used")
    created_at: datetime = Field(default_factory=datetime.now, description="Session creation timestamp")


class InteractRequest(BaseModel):
    """Request model for browser interaction commands."""
    message: str = Field(..., min_length=1, max_length=5000, description="Natural language command to execute")
    
    @validator('message')
    def validate_message(cls, v):
        if not v or not v.strip():
            raise ValueError('Message cannot be empty or whitespace only')
        return v.strip()


class CommandExecuted(BaseModel):
    """Model for an executed command."""
    command: str = Field(..., description="The Playwright command that was executed")
    timestamp: datetime = Field(default_factory=datetime.now, description="When the command was executed")
    success: bool = Field(..., description="Whether the command succeeded")


class InteractResponse(BaseModel):
    """Response model for browser interaction."""
    status: str = Field(..., description="Status of the operation: success, failure, or partial")
    session_id: str = Field(..., description="The session identifier")
    commands_executed: List[str] = Field(default_factory=list, description="List of commands executed")
    error: Optional[str] = Field(None, description="Error message if status is failure")
    code: int = Field(..., description="HTTP-like status code")
    execution_time_seconds: Optional[float] = Field(None, description="Total execution time")


class ErrorResponse(BaseModel):
    """Standard error response model."""
    error: str = Field(..., description="Error message")
    status: str = Field(default="failure", description="Status indicator")
    code: int = Field(..., description="HTTP-like status code")
    session_id: Optional[str] = Field(None, description="Session ID if applicable")


class SessionStatusResponse(BaseModel):
    """Response model for session status."""
    session_id: str = Field(..., description="The session identifier")
    exists: bool = Field(..., description="Whether the session exists")
    active: bool = Field(default=False, description="Whether the session is active")
    commands_executed_count: int = Field(default=0, description="Number of commands executed")
    created_at: Optional[datetime] = Field(None, description="Session creation time")
    last_activity: Optional[datetime] = Field(None, description="Last activity time")


INTERACT_SYSTEM_PROMPT = """
    *`*Role**  
    You are an expert UI tester working in Playwright Python. Your task is to generate commands for the active browser tab.

    **Input Format**  
    Natural language instruction (e.g., "Take screenshot of header after login").

    **Output Rules**  
    1. EXCLUSIVELY output a SINGLE async Playwright Python command using the existing `page` object followed by the next input command on a new line.
    2. Format: `<command> \n <next_input>`
    3. DO NOT USE MARKDOWN CODE BLOCKS. DO NOT USE TRIPLE BACKTICKS (```). Output raw commands only 1 step at a time.
    4. No explanations, comments, or formatting symbols. Strictly follow the format.
    5. ALWAYS start by navigating to the desired page using `await page.goto(<URL>)`.
    6. Prioritize the following locator methods:
        - role-based locators (e.g., `get_by_role`)
        - text-based locators (e.g., `get_by_text`)
    7. Ensure proper waits:
        - `wait_for_timeout(2000)` for fixed delays
        - `wait_for_load_state("networkidle")`
        - `wait_for_selector()` with a 2s timeout
    8. Chain related actions using:
        - `.first()`
        - `.nth(index)`
        - `.filter()`
    9. Check if elements exist before interacting:
        - `if locator.count() > 0:`
        - `if locator.is_visible():`
        - `if locator.is_enabled():`
    10. Replace `<variable_value>` with the actual value in the command.
    11. If an input is involved, confirm that the field is filled before submitting.
    12. If filling a field, ensure the field is visible before filling it. If a field is not visible, a click action might be needed to make it visible.

    **Examples**

    1. 
    Input: "log in into https://practicetestautomation.com/practice-test-login/ with username student and password Password123"
    Output: "await page.goto("https://practicetestautomation.com/practice-test-login/") \n Fill out the username field with 'student'."
    
    Input: "Fill out the username field with 'student'."
    Output: "await page.get_by_role('textbox', name='Username').fill('student') \n Wait for the password field to be visible. If already visible, continue."
    
    Input: "Fill in the password field with Password123."
    Output: "await page.get_by_role('textbox', name='Password').fill('Password123') \n Wait for the submit button to be enabled/ If already enabled, click on the submit/log in button."
    
    Input: "Wait for the submit button to be enabled/ If already enabled, click on the submit/log in button."
    Output: "await page.get_by_role('button', name='Submit').click() \n print('#completed')"
    
    Input: "Set action_done to True."
    Output: "print('#completed') \n Done."
   
    2.  
    Input: "log in into reddit.com with username boogieman and password abcd1234 and navigate to popular"
    Output: "await page.goto('https://reddit.com') \n Verify that the Reddit homepage has loaded."

    Input: "Verify that the Reddit homepage has loaded."
    Output: "await page.get_by_role('link', name='Log In').wait_for(timeout=5000) \n Locate the 'Log In' link."

    Input: "Locate the 'Log In' link."
    Output: "await page.get_by_role('link', name='Log In').click() \n Wait for the username field to become visible."

    Input: "Wait for the username field to become visible."
    Output: "await page.get_by_role('textbox', name='Username').wait_for(timeout=5000) \n Fill in the username field with 'boggiemann'."

    Input: "Fill in the username field with 'boggiemann'."
    Output: "await page.get_by_role('textbox', name='Username').fill('boggiemann') \n Wait for the password field to become visible."

    Input: "Wait for the password field to become visible."
    Output: "await page.get_by_role('textbox', name='Password').wait_for(timeout=5000) \n Fill in the password field with 'abcd1234'."

    Input: "Fill in the password field with 'abcd1234'."
    Output: "await page.get_by_role('textbox', name='Password').fill('abcd1234') \n Wait a moment before submitting."

    Input: "Wait a moment before submitting."
    Output: "await page.wait_for_timeout(1000) \n Click the 'Log In' button."

    Input: "Click the 'Log In' button."
    Output: "await page.get_by_role('button', name='Log In').click() \n Wait a moment after submitting."

    Input: "Wait a moment after submitting."
    Output: "await page.wait_for_timeout(1000) \n Navigate to Popular."

    Input: "Navigate to Popular."
    Output: "await page.locator('a:has-text(\"Popular\")').click() \n Wait for the 'Popular' page to load."

    Input: "Wait for the 'Popular' page to load."
    Output: "await page.wait_for_load_state('networkidle') \n Set action_done to True."
    
    Input: "Set action_done to True."
    Output: "print('#completed') \n Done."
    """

JAVASCRIPT_INTERACT_PROMPT = """
    **Role**  
    You are an expert browser automation assistant. You generate JavaScript-based browser interaction commands that are more reliable than traditional selectors.

    **IMPORTANT: You will receive a list of ALL visible interactive elements on the page with their attributes (id, name, placeholder, text, etc.). Use this information to generate accurate commands!**

    **Input Format**  
    Natural language instruction + **Current Page Elements** list showing all visible inputs, buttons, links with their attributes.

    **Output Rules**  
    1. Output a SINGLE JSON command object followed by the next step description on a new line.
    2. Format: `<JSON command> \\n <next_step_description>`
    3. DO NOT USE MARKDOWN CODE BLOCKS. Output raw JSON only.
    4. ALWAYS look at the "Current Page Elements" list to find the exact selectors available.
    5. Each command must be a valid JSON object with these fields:
       - "action": One of ["goto", "click", "fill", "select", "press_key", "wait", "wait_element", "switch_tab", "close_tab", "close_other_tabs", "completed"]
       - "selector": Use EXACT values from the page elements list (id, name, placeholder, text, class)
       - "selector_type": "css", "text", "placeholder", "label", "xpath"
       - "value": Value for fill/select actions or URL for goto
       - "timeout": Milliseconds for wait actions (default 2000)
       - "tab_index": Tab number for switch_tab or close_tab actions (0-based index)
    
    6. When selecting elements:
       - If you see placeholder="X" in the list, use selector_type="placeholder" and selector="X"
       - If you see text="X" in the list, use selector_type="text" and selector="X"
       - If you see id="X" in the list, use selector_type="css" and selector="#X"
       - If you see name="X" in the list, use selector_type="css" and selector="[name='X']"
    
    7. About opening links in new tabs:
       - If an element shows "⚠️ OPENS_IN_NEW_TAB (target=_blank)", it ALREADY opens in a new tab
       - DO NOT add "open_in_new_tab": true for elements that already have this marker
       - Only use "open_in_new_tab": true if you need a link to open in a new tab AND it doesn't have the marker
    
    8. About managing multiple tabs:
       - You will see "**Open Tabs**" section if there are multiple tabs open
       - Use "close_other_tabs" to close all tabs except the current one (RECOMMENDED when too many tabs are open)
       - Use "switch_tab" with tab_index to switch to a specific tab
       - Use "close_tab" without tab_index to close current tab, or with tab_index to close specific tab
       - Tab indices are 0-based (first tab = 0, second tab = 1, etc.)
    
    9. About handling dropdowns:
       - If an element shows "🔽 DROPDOWN" it's a select/dropdown element
       - Elements with "🔽 DROPDOWN options=[...]" show available options
       - Use "select" action for dropdowns, NOT "click" or "fill"
       - For select action: use the OPTION TEXT as the value (e.g., "United States", "Blue", "Option 1")
       - selector_type can be "css", "text", "label" to find the dropdown
       - Example: {"action": "select", "selector": "Country", "selector_type": "label", "value": "United States"}
    
    **Command Examples:**
    
    Navigate:
    {"action": "goto", "value": "https://example.com"}
    
    Click by CSS:
    {"action": "click", "selector": "button.login-btn", "selector_type": "css"}
    
    Click by text (normal):
    {"action": "click", "selector": "Sign in", "selector_type": "text"}
    
    Click link that ALREADY opens in new tab (don't add open_in_new_tab):
    // Element list shows: [5] a - text="Documentation", ⚠️ OPENS_IN_NEW_TAB (target=_blank)
    {"action": "click", "selector": "Documentation", "selector_type": "text"}
    
    Click link and force open in new tab (only if it doesn't already):
    // Element list shows: [3] a - text="About", href="https://example.com/about"
    {"action": "click", "selector": "About", "selector_type": "text", "open_in_new_tab": true}
    
    Fill by placeholder:
    {"action": "fill", "selector": "Enter your email", "selector_type": "placeholder", "value": "user@example.com"}
    
    Fill by CSS:
    {"action": "fill", "selector": "input[name='username']", "selector_type": "css", "value": "testuser"}
    
    Fill by label:
    {"action": "fill", "selector": "Username", "selector_type": "label", "value": "testuser"}
    
    Select dropdown by label:
    // Element list shows: [8] select - name="country", 🔽 DROPDOWN options=[United States, Canada, Mexico, ...]
    {"action": "select", "selector": "country", "selector_type": "css", "value": "United States"}
    
    Select dropdown by CSS:
    {"action": "select", "selector": "select[name='color']", "selector_type": "css", "value": "Blue"}
    
    Select custom dropdown by text:
    // Element list shows: [12] div - role=combobox, aria-label="Select language", 🔽 DROPDOWN
    {"action": "select", "selector": "Select language", "selector_type": "label", "value": "English"}
    
    Press key:
    {"action": "press_key", "value": "Enter"}
    
    Wait for element:
    {"action": "wait_element", "selector": "button.submit", "selector_type": "css", "timeout": 5000}
    
    General wait:
    {"action": "wait", "timeout": 2000}
    
    Task completed:
    {"action": "completed"}
    
    Switch to tab 0 (first tab):
    {"action": "switch_tab", "tab_index": 0}
    
    Close current tab:
    {"action": "close_tab"}
    
    Close specific tab (tab 2):
    {"action": "close_tab", "tab_index": 2}
    
    Close all other tabs (keep only current):
    {"action": "close_other_tabs"}

    **Full Example Flow:**
    
    Input: "Go to example.com and click the login button"
    Output: {"action": "goto", "value": "https://example.com"} \\n Wait for page to load and locate login button
    
    Input: "Wait for page to load and locate login button"
    Output: {"action": "wait_element", "selector": "Log in", "selector_type": "text", "timeout": 3000} \\n Click the login button
    
    Input: "Click the login button"
    Output: {"action": "click", "selector": "Log in", "selector_type": "text"} \\n Wait for username field
    
    Input: "Wait for username field"
    Output: {"action": "wait_element", "selector": "username", "selector_type": "placeholder", "timeout": 3000} \\n Fill username with provided value
    
    Input: "Fill username with 'testuser'"
    Output: {"action": "fill", "selector": "username", "selector_type": "placeholder", "value": "testuser"} \\n Fill password field
    
    Input: "Fill password field with 'password123'"
    Output: {"action": "fill", "selector": "password", "selector_type": "placeholder", "value": "password123"} \\n Submit the form
    
    Input: "Submit the form"
    Output: {"action": "press_key", "value": "Enter"} \\n Wait for login to complete
    
    Input: "Wait for login to complete"
    Output: {"action": "wait", "timeout": 2000} \\n Mark as completed
    
    Input: "Mark as completed"
    Output: {"action": "completed"} \\n Done
    
    **Important Notes:**
    - Always use the simplest and most reliable selector
    - Prefer text-based selectors when possible (more robust than CSS)
    - Add waits between major actions
    - Use wait_element to ensure elements are present before interacting
    - Mark task as completed when the goal is achieved
    """
    


@dataclass
class Session:
    """Represents a browser automation session."""
    page: Optional[Page] = None
    commands_executed: List[str] = field(default_factory=list)
    page_snapshot: str = ""
    retry_count: int = 0
    action_done: bool = False
    llm: Optional[llm] = None
    last_command: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    last_activity: datetime = field(default_factory=datetime.now)
    use_javascript: bool = True  # Use JavaScript execution by default
    browser_context: Optional[Any] = None  # Browser context for managing multiple pages
    all_pages: List[Page] = field(default_factory=list)  # Track all open pages/tabs


class SessionManager:
    """Manages browser sessions with automatic cleanup."""
    
    def __init__(self):
        self.sessions: Dict[str, Session] = {}
        self._cleanup_task: Optional[asyncio.Task] = None

    def create_session(self) -> str:
        """Create a new browser session."""
        session_id = str(uuid.uuid4())
        self.sessions[session_id] = Session()
        logger.info(f"Created new session: {session_id}")
        return session_id
    
    def get_session(self, session_id: str) -> Optional[Session]:
        """Get a session by ID."""
        session = self.sessions.get(session_id)
        if session:
            session.last_activity = datetime.now()
        return session
    
    async def cleanup_expired_sessions(self):
        """Remove sessions that have been inactive for too long."""
        while True:
            try:
                await asyncio.sleep(300)  # Check every 5 minutes
                current_time = datetime.now()
                expired_sessions = []
                
                for session_id, session in self.sessions.items():
                    time_inactive = current_time - session.last_activity
                    if time_inactive > timedelta(minutes=config.SESSION_TIMEOUT_MINUTES):
                        expired_sessions.append(session_id)
                
                for session_id in expired_sessions:
                    await self.close_session(session_id)
                    logger.info(f"Cleaned up expired session: {session_id}")
            except Exception as e:
                logger.error(f"Error in session cleanup: {e}")
    
    async def close_session(self, session_id: str):
        """Close and remove a session."""
        if session_id in self.sessions:
            session = self.sessions[session_id]
            # Close all pages
            for page in session.all_pages:
                try:
                    await page.close()
                except Exception as e:
                    logger.error(f"Error closing page: {e}")
            
            if session.page:
                try:
                    await session.page.close()
                except Exception as e:
                    logger.error(f"Error closing main page for session {session_id}: {e}")
            
            # Close browser context if it exists
            if session.browser_context:
                try:
                    await session.browser_context.close()
                except Exception as e:
                    logger.error(f"Error closing browser context: {e}")
            
            del self.sessions[session_id]
            logger.info(f"Closed session: {session_id}")
    
    
session_manager = SessionManager()


class TabManager:
    """Manages browser tabs/pages within a session."""
    
    @staticmethod
    async def get_all_pages(session: 'Session') -> List[Dict[str, Any]]:
        """Get information about all open pages/tabs."""
        try:
            if not session.browser_context:
                return []
            
            pages = session.browser_context.pages
            page_info = []
            
            # Clean up closed pages from tracking list
            session.all_pages = [p for p in session.all_pages if not p.is_closed()]
            
            for idx, page in enumerate(pages):
                try:
                    # Skip closed pages
                    if page.is_closed():
                        continue
                    
                    title = await page.title()
                    url = page.url
                    is_current = page == session.page
                    
                    page_info.append({
                        "index": idx,
                        "title": title[:100],
                        "url": url,
                        "is_current": is_current
                    })
                except Exception as e:
                    logger.warning(f"Error getting page info for tab {idx}: {e}")
            
            return page_info
        except Exception as e:
            logger.error(f"Error getting all pages: {e}")
            return []
    
    @staticmethod
    async def switch_to_tab(session: 'Session', tab_index: int) -> bool:
        """Switch to a specific tab by index."""
        try:
            if not session.browser_context:
                return False
            
            pages = session.browser_context.pages
            if 0 <= tab_index < len(pages):
                session.page = pages[tab_index]
                await session.page.bring_to_front()
                logger.info(f"Switched to tab {tab_index}: {session.page.url}")
                return True
            else:
                logger.error(f"Tab index {tab_index} out of range (0-{len(pages)-1})")
                return False
        except Exception as e:
            logger.error(f"Error switching to tab {tab_index}: {e}")
            return False
    
    @staticmethod
    async def close_tab(session: 'Session', tab_index: Optional[int] = None) -> bool:
        """Close a specific tab or the current tab."""
        try:
            if not session.browser_context:
                return False
            
            pages = session.browser_context.pages
            
            # Filter out closed pages
            open_pages = [p for p in pages if not p.is_closed()]
            
            if tab_index is None:
                # Close current tab
                if session.page and not session.page.is_closed():
                    await session.page.close()
                    # Switch to first remaining tab
                    remaining = [p for p in open_pages if p != session.page and not p.is_closed()]
                    if remaining:
                        session.page = remaining[0]
                        await session.page.bring_to_front()
                    logger.info("Closed current tab")
                    return True
            else:
                # Close specific tab
                if 0 <= tab_index < len(open_pages):
                    page_to_close = open_pages[tab_index]
                    
                    if page_to_close.is_closed():
                        logger.warning(f"Tab {tab_index} is already closed")
                        return False
                    
                    was_current = page_to_close == session.page
                    await page_to_close.close()
                    
                    # Update current page if we closed it
                    if was_current:
                        remaining = [p for p in open_pages if p != page_to_close and not p.is_closed()]
                        if remaining:
                            session.page = remaining[0]
                            await session.page.bring_to_front()
                    
                    logger.info(f"Closed tab {tab_index}")
                    return True
                else:
                    logger.error(f"Tab index {tab_index} out of range (have {len(open_pages)} tabs)")
                    return False
        except Exception as e:
            logger.error(f"Error closing tab: {e}")
            return False
    
    @staticmethod
    async def close_other_tabs(session: 'Session') -> int:
        """Close all tabs except the current one."""
        try:
            if not session.browser_context or not session.page:
                return 0
            
            pages = session.browser_context.pages
            current_page = session.page
            closed_count = 0
            
            for page in pages:
                if page != current_page and not page.is_closed():
                    try:
                        await page.close()
                        closed_count += 1
                        logger.debug(f"Closed tab: {page.url}")
                    except Exception as e:
                        logger.warning(f"Error closing tab {page.url}: {e}")
            
            logger.info(f"Closed {closed_count} other tabs, kept current tab")
            
            # Clean up the tracking list
            session.all_pages = [p for p in session.all_pages if not p.is_closed()]
            
            return closed_count
        except Exception as e:
            logger.error(f"Error closing other tabs: {e}")
            return 0


class DOMInspector:
    """Extracts detailed page information for the LLM."""
    
    @staticmethod
    async def get_page_elements(page: Page) -> str:
        """
        Extract all interactive and visible elements from the page.
        
        Returns:
            Formatted string with element information
        """
        try:
            js_code = """
            () => {
                const elements = [];
                const selectors = [
                    'input', 'button', 'a', 'textarea', 'select',
                    '[role="button"]', '[role="link"]', '[role="textbox"]',
                    '[role="combobox"]', '[role="listbox"]', '[role="option"]',
                    '[onclick]', '[type="submit"]'
                ];
                
                const allElements = document.querySelectorAll(selectors.join(','));
                
                allElements.forEach((el, index) => {
                    const rect = el.getBoundingClientRect();
                    
                    // Only include visible elements
                    if (rect.width > 0 && rect.height > 0 && 
                        window.getComputedStyle(el).visibility !== 'hidden' &&
                        window.getComputedStyle(el).display !== 'none') {
                        
                        const info = {
                            index: index,
                            tag: el.tagName.toLowerCase(),
                            type: el.type || null,
                            id: el.id || null,
                            class: el.className || null,
                            name: el.name || null,
                            placeholder: el.placeholder || null,
                            value: el.value || null,
                            text: el.textContent?.trim().substring(0, 100) || null,
                            ariaLabel: el.getAttribute('aria-label') || null,
                            role: el.getAttribute('role') || null,
                            href: el.href || null,
                            target: el.target || null,  // Show if link opens in new tab
                            opensInNewTab: (el.tagName.toLowerCase() === 'a' && el.target === '_blank') || null
                        };
                        
                        // For select elements, add options
                        if (el.tagName.toLowerCase() === 'select') {
                            const options = Array.from(el.options).map(opt => opt.text.trim());
                            if (options.length > 0) {
                                info.options = options.slice(0, 10);  // Limit to 10 options
                                info.isDropdown = true;
                            }
                        }
                        
                        // For elements with role="combobox" or "listbox", mark as dropdown
                        if (el.getAttribute('role') === 'combobox' || el.getAttribute('role') === 'listbox') {
                            info.isDropdown = true;
                        }
                        
                        // Clean up the info object
                        Object.keys(info).forEach(key => {
                            if (info[key] === null || info[key] === '') {
                                delete info[key];
                            }
                        });
                        
                        if (Object.keys(info).length > 2) { // More than just index and tag
                            elements.push(info);
                        }
                    }
                });
                
                return elements.slice(0, 50); // Limit to 50 elements
            }
            """
            
            elements = await page.evaluate(js_code)
            
            if not elements:
                return "No interactive elements found on the page."
            
            # Format elements nicely
            output = "**Visible Interactive Elements on Page:**\n\n"
            for elem in elements:
                elem_desc = f"[{elem.get('index')}] {elem.get('tag')}"
                
                details = []
                if elem.get('type'):
                    details.append(f"type={elem['type']}")
                if elem.get('id'):
                    details.append(f"id={elem['id']}")
                if elem.get('name'):
                    details.append(f"name={elem['name']}")
                if elem.get('placeholder'):
                    details.append(f"placeholder=\"{elem['placeholder']}\"")
                if elem.get('text') and not elem.get('isDropdown'):
                    details.append(f"text=\"{elem['text'][:50]}\"")
                if elem.get('ariaLabel'):
                    details.append(f"aria-label=\"{elem['ariaLabel']}\"")
                if elem.get('role'):
                    details.append(f"role={elem['role']}")
                if elem.get('opensInNewTab'):
                    details.append(f"⚠️ OPENS_IN_NEW_TAB (target=_blank)")
                if elem.get('isDropdown'):
                    if elem.get('options'):
                        options_str = ', '.join(elem['options'][:5])  # Show first 5 options
                        if len(elem['options']) > 5:
                            options_str += f", ... ({len(elem['options'])} total)"
                        details.append(f"🔽 DROPDOWN options=[{options_str}]")
                    else:
                        details.append(f"🔽 DROPDOWN")
                if elem.get('class') and not elem.get('isDropdown'):
                    details.append(f"class=\"{elem['class'][:30]}\"")
                
                if details:
                    elem_desc += f" - {', '.join(details)}"
                
                output += elem_desc + "\n"
            
            return output
            
        except Exception as e:
            logger.error(f"Failed to extract page elements: {e}")
            return "Failed to extract page elements."


class JavaScriptExecutor:
    """Executes browser interactions using JavaScript, similar to Cursor's approach."""
    
    @staticmethod
    async def select_dropdown(page: Page, selector: str, value: str, selector_type: str = "css") -> bool:
        """
        Select an option in a dropdown (both native select and custom dropdowns).
        
        Args:
            page: The Playwright page object
            selector: The dropdown selector
            value: The option text or value to select
            selector_type: Type of selector
        
        Returns:
            True if successful, False otherwise
        """
        try:
            js_code = """
            (args) => {
                const { selector, value, selectorType } = args;
                let element = null;
                
                // Find the dropdown element
                if (selectorType === 'css') {
                    element = document.querySelector(selector);
                } else if (selectorType === 'text') {
                    const elements = Array.from(document.querySelectorAll('select, [role="combobox"], [role="listbox"]'));
                    element = elements.find(el => {
                        const text = el.textContent?.trim() || '';
                        const label = el.getAttribute('aria-label') || '';
                        return text.includes(selector) || label.includes(selector);
                    });
                } else if (selectorType === 'label') {
                    const label = Array.from(document.querySelectorAll('label')).find(l => l.textContent.includes(selector));
                    if (label) {
                        const forId = label.getAttribute('for');
                        element = forId ? document.getElementById(forId) : label.querySelector('select, [role="combobox"]');
                    }
                }
                
                if (!element) {
                    return { success: false, error: 'Dropdown not found' };
                }
                
                element.scrollIntoView({behavior: 'smooth', block: 'center'});
                
                // Handle native select element
                if (element.tagName.toLowerCase() === 'select') {
                    const options = Array.from(element.options);
                    const option = options.find(opt => 
                        opt.text.trim() === value || 
                        opt.value === value ||
                        opt.text.trim().includes(value)
                    );
                    
                    if (option) {
                        element.value = option.value;
                        element.dispatchEvent(new Event('change', { bubbles: true }));
                        element.dispatchEvent(new Event('input', { bubbles: true }));
                        return { success: true, type: 'native', selected: option.text };
                    } else {
                        return { success: false, error: `Option "${value}" not found`, availableOptions: options.map(o => o.text) };
                    }
                }
                
                // Handle custom dropdown (role="combobox")
                if (element.getAttribute('role') === 'combobox' || element.getAttribute('role') === 'listbox') {
                    // Click to open dropdown
                    element.click();
                    
                    // Wait a bit for dropdown to open
                    setTimeout(() => {
                        // Find and click the option
                        const optionElements = document.querySelectorAll('[role="option"]');
                        const targetOption = Array.from(optionElements).find(opt => 
                            opt.textContent.trim() === value || 
                            opt.textContent.trim().includes(value)
                        );
                        
                        if (targetOption) {
                            targetOption.click();
                        }
                    }, 100);
                    
                    return { success: true, type: 'custom', attempted: value };
                }
                
                return { success: false, error: 'Not a dropdown element' };
            }
            """
            result = await page.evaluate(js_code, {"selector": selector, "value": value, "selectorType": selector_type})
            
            if result.get('success'):
                logger.info(f"Selected '{value}' in dropdown '{selector}' ({result.get('type')} dropdown)")
                await page.wait_for_timeout(300)  # Brief wait for any handlers
                return True
            else:
                logger.error(f"Dropdown selection failed: {result.get('error')}")
                if result.get('availableOptions'):
                    logger.info(f"Available options: {result.get('availableOptions')}")
                return False
                
        except Exception as e:
            logger.error(f"Dropdown selection failed: {e}")
            return False
    
    @staticmethod
    async def click_element(page: Page, selector: str, selector_type: str = "css", open_in_new_tab: bool = False) -> bool:
        """
        Click an element using JavaScript with fallback to Playwright native click.
        
        Args:
            page: The Playwright page object
            selector: The element selector
            selector_type: Type of selector (css, xpath, text, role)
        
        Returns:
            True if successful, False otherwise
        """
        try:
            # First try: JavaScript click with multiple event types
            js_code = """
            (args) => {
                const { selector, selectorType, openInNewTab } = args;
                let element = null;
                
                if (selectorType === 'css') {
                    element = document.querySelector(selector);
                } else if (selectorType === 'xpath') {
                    element = document.evaluate(selector, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                } else if (selectorType === 'text') {
                    // Find clickable elements with matching text
                    const clickableSelectors = 'a, button, [role="button"], [role="link"], [onclick], input[type="submit"], input[type="button"]';
                    const elements = Array.from(document.querySelectorAll(clickableSelectors));
                    element = elements.find(el => {
                        const text = el.textContent.trim();
                        const ariaLabel = el.getAttribute('aria-label') || '';
                        return text === selector || text.includes(selector) || ariaLabel.includes(selector);
                    });
                    
                    // If not found in clickable elements, try all elements
                    if (!element) {
                        const allElements = Array.from(document.querySelectorAll('*'));
                        element = allElements.find(el => el.textContent.trim() === selector);
                    }
                }
                
                if (element) {
                    element.scrollIntoView({behavior: 'smooth', block: 'center'});
                    
                    // Check if link already opens in new tab
                    const alreadyOpensInNewTab = element.tagName === 'A' && 
                        (element.target === '_blank' || element.rel?.includes('noopener'));
                    
                    // If it's a link and we want new tab behavior
                    if (element.tagName === 'A' && openInNewTab && !alreadyOpensInNewTab) {
                        // Modify the link to open in new tab
                        const originalTarget = element.target;
                        element.target = '_blank';
                        element.rel = 'noopener noreferrer';
                        
                        // Click it
                        element.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
                        element.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
                        element.click();
                        element.dispatchEvent(new MouseEvent('click', { bubbles: true }));
                        
                        // Restore original target
                        element.target = originalTarget;
                        
                        return {
                            success: true,
                            tagName: element.tagName,
                            text: element.textContent.trim().substring(0, 50),
                            openedInNewTab: true,
                            wasModified: true
                        };
                    } else {
                        // Normal click or already opens in new tab
                        element.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
                        element.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
                        element.click();
                        element.dispatchEvent(new MouseEvent('click', { bubbles: true }));
                        
                        return {
                            success: true,
                            tagName: element.tagName,
                            text: element.textContent.trim().substring(0, 50),
                            openedInNewTab: alreadyOpensInNewTab,
                            wasModified: false
                        };
                    }
                }
                return { success: false, error: 'Element not found' };
            }
            """
            result = await page.evaluate(js_code, {
                "selector": selector, 
                "selectorType": selector_type,
                "openInNewTab": open_in_new_tab
            })
            
            if result.get('success'):
                new_tab_info = ""
                if result.get('openedInNewTab'):
                    if result.get('wasModified'):
                        new_tab_info = " [Modified to open in new tab]"
                    else:
                        new_tab_info = " [Already opens in new tab - no modification needed]"
                logger.info(f"JavaScript click successful on '{selector}' ({result.get('tagName')}){new_tab_info}")
                await page.wait_for_timeout(500)  # Brief wait for any JavaScript handlers
                return True
            
            # Fallback: Try Playwright's native click
            logger.warning(f"JavaScript click didn't find element, trying Playwright native click")
            
            if selector_type == "text":
                # Try to find by text using Playwright
                try:
                    # Try as button first
                    await page.get_by_role("button", name=selector).click(timeout=2000)
                    logger.info(f"Playwright click successful on button with text '{selector}'")
                    return True
                except:
                    try:
                        # Try as link
                        await page.get_by_role("link", name=selector).click(timeout=2000)
                        logger.info(f"Playwright click successful on link with text '{selector}'")
                        return True
                    except:
                        try:
                            # Try get_by_text
                            await page.get_by_text(selector, exact=False).first.click(timeout=2000)
                            logger.info(f"Playwright click successful using get_by_text '{selector}'")
                            return True
                        except:
                            pass
            
            elif selector_type == "css":
                try:
                    await page.locator(selector).first.click(timeout=2000)
                    logger.info(f"Playwright click successful on CSS selector '{selector}'")
                    return True
                except:
                    pass
            
            logger.error(f"All click attempts failed for '{selector}'")
            return False
            
        except Exception as e:
            logger.error(f"JavaScript click failed: {e}")
            return False
    
    @staticmethod
    async def fill_input(page: Page, selector: str, value: str, selector_type: str = "css") -> bool:
        """
        Fill an input field using JavaScript.
        
        Args:
            page: The Playwright page object
            selector: The element selector
            value: The value to fill
            selector_type: Type of selector (css, xpath, placeholder, label)
        
        Returns:
            True if successful, False otherwise
        """
        try:
            js_code = """
            (args) => {
                const { selector, value, selectorType } = args;
                let element = null;
                
                if (selectorType === 'css') {
                    element = document.querySelector(selector);
                } else if (selectorType === 'xpath') {
                    element = document.evaluate(selector, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                } else if (selectorType === 'placeholder') {
                    // Find input/textarea with matching placeholder (exact or partial match)
                    const inputs = Array.from(document.querySelectorAll('input, textarea'));
                    element = inputs.find(el => {
                        const ph = el.getAttribute('placeholder');
                        return ph && ph.includes(selector);
                    });
                } else if (selectorType === 'label') {
                    const label = Array.from(document.querySelectorAll('label')).find(l => l.textContent.includes(selector));
                    if (label) {
                        element = document.getElementById(label.getAttribute('for')) || label.querySelector('input, textarea, select');
                    }
                }
                
                if (element) {
                    element.scrollIntoView({behavior: 'smooth', block: 'center'});
                    element.focus();
                    element.value = value;
                    element.dispatchEvent(new Event('input', { bubbles: true }));
                    element.dispatchEvent(new Event('change', { bubbles: true }));
                    return true;
                }
                return false;
            }
            """
            result = await page.evaluate(js_code, {"selector": selector, "value": value, "selectorType": selector_type})
            logger.debug(f"JavaScript fill '{selector}' with '{value}' ({selector_type}): {result}")
            return result
        except Exception as e:
            logger.error(f"JavaScript fill failed: {e}")
            return False
    
    @staticmethod
    async def press_key(page: Page, key: str) -> bool:
        """
        Press a keyboard key using JavaScript.
        
        Args:
            page: The Playwright page object
            key: The key to press (e.g., 'Enter', 'Escape')
        
        Returns:
            True if successful, False otherwise
        """
        try:
            js_code = """
            (args) => {
                const { key } = args;
                const activeElement = document.activeElement;
                if (activeElement) {
                    const event = new KeyboardEvent('keydown', {
                        key: key,
                        code: key,
                        bubbles: true,
                        cancelable: true
                    });
                    activeElement.dispatchEvent(event);
                    
                    const keyupEvent = new KeyboardEvent('keyup', {
                        key: key,
                        code: key,
                        bubbles: true,
                        cancelable: true
                    });
                    activeElement.dispatchEvent(keyupEvent);
                    return true;
                }
                return false;
            }
            """
            result = await page.evaluate(js_code, {"key": key})
            logger.debug(f"JavaScript key press '{key}': {result}")
            return result
        except Exception as e:
            logger.error(f"JavaScript key press failed: {e}")
            return False
    
    @staticmethod
    async def wait_for_element(page: Page, selector: str, selector_type: str = "css", timeout: int = 5000) -> bool:
        """
        Wait for an element to appear using JavaScript polling.
        
        Args:
            page: The Playwright page object
            selector: The element selector
            selector_type: Type of selector
            timeout: Maximum wait time in milliseconds
        
        Returns:
            True if element found, False otherwise
        """
        try:
            js_code = """
            (args) => {
                const { selector, selectorType, timeout } = args;
                return new Promise((resolve) => {
                    const startTime = Date.now();
                    const interval = setInterval(() => {
                        let element = null;
                        
                        if (selectorType === 'css') {
                            element = document.querySelector(selector);
                        } else if (selectorType === 'text') {
                            const elements = Array.from(document.querySelectorAll('*'));
                            element = elements.find(el => el.textContent.trim().includes(selector));
                        }
                        
                        if (element) {
                            clearInterval(interval);
                            resolve(true);
                        } else if (Date.now() - startTime > timeout) {
                            clearInterval(interval);
                            resolve(false);
                        }
                    }, 100);
                });
            }
            """
            result = await page.evaluate(js_code, {"selector": selector, "selectorType": selector_type, "timeout": timeout})
            logger.debug(f"JavaScript wait for '{selector}' ({selector_type}): {result}")
            return result
        except Exception as e:
            logger.error(f"JavaScript wait for element failed: {e}")
            return False
    
    @staticmethod
    async def get_element_info(page: Page, selector: str, selector_type: str = "css") -> Optional[Dict[str, Any]]:
        """
        Get information about an element using JavaScript.
        
        Args:
            page: The Playwright page object
            selector: The element selector
            selector_type: Type of selector
        
        Returns:
            Dictionary with element info or None
        """
        try:
            js_code = """
            (args) => {
                const { selector, selectorType } = args;
                let element = null;
                
                if (selectorType === 'css') {
                    element = document.querySelector(selector);
                } else if (selectorType === 'text') {
                    const elements = Array.from(document.querySelectorAll('*'));
                    element = elements.find(el => el.textContent.trim().includes(selector));
                }
                
                if (element) {
                    const rect = element.getBoundingClientRect();
                    return {
                        tagName: element.tagName,
                        text: element.textContent.trim(),
                        value: element.value || null,
                        visible: rect.width > 0 && rect.height > 0,
                        enabled: !element.disabled,
                        x: rect.x,
                        y: rect.y,
                        width: rect.width,
                        height: rect.height
                    };
                }
                return null;
            }
            """
            result = await page.evaluate(js_code, {"selector": selector, "selectorType": selector_type})
            logger.debug(f"JavaScript element info for '{selector}': {result}")
            return result
        except Exception as e:
            logger.error(f"JavaScript get element info failed: {e}")
            return None


class CommandExecutor:
    """Safely executes Playwright commands."""
    
    @staticmethod
    async def execute(page: Page, command: str) -> None:
        """
        Execute a Playwright command safely.
        
        Args:
            page: The Playwright page object
            command: The command string to execute
        
        Raises:
            ValueError: If command is invalid or unsafe
            Exception: If command execution fails
        """
        command = command.strip()
        
        # Security check: only allow specific Playwright methods
        allowed_methods = [
            'goto', 'click', 'fill', 'press', 'wait_for_timeout', 
            'wait_for_load_state', 'wait_for_selector', 'get_by_role',
            'get_by_text', 'get_by_label', 'locator', 'keyboard',
            'wait_for', 'is_visible', 'is_enabled', 'count',
            'first', 'last', 'nth', 'filter', 'accessibility'
        ]
        
        # Check if command starts with 'page.'
        if not command.startswith('page.'):
            raise ValueError(f"Command must start with 'page.': {command}")
        
        # Extract the method name
        method_name = command.split('(')[0].split('.')[1] if '.' in command else None
        if not method_name or method_name not in allowed_methods:
            raise ValueError(f"Method '{method_name}' is not allowed")
        
        # Create safe execution environment
        safe_globals = {
            'page': page,
            '__builtins__': {
                'True': True,
                'False': False,
                'None': None,
                'str': str,
                'int': int,
                'float': float,
                'bool': bool,
            }
        }
        
        try:
            await eval(command, safe_globals, {})
            logger.debug(f"Successfully executed: {command}")
        except Exception as e:
            logger.error(f"Failed to execute command '{command}': {e}")
            raise


class ResponseParser:
    """Parse LLM responses into commands and next steps."""
    
    @staticmethod
    def parse_response(response: str) -> tuple[Optional[str], Optional[str], bool]:
        """
        Parse LLM response into command and next action.
        
        Args:
            response: Raw LLM response text
            
        Returns:
            Tuple of (command, next_action, is_completed)
        """
        try:
            lines = [line.strip() for line in response.split('\n') if line.strip()]
            
            if not lines:
                logger.warning("Empty response from LLM")
                return None, None, False
            
            # Check for completion marker
            first_line = lines[0]
            if '#completed' in first_line.lower() or 'print(\'#completed\')' in first_line.lower():
                logger.info("Task marked as completed")
                return None, None, True
            
            # Parse command and next action
            command_line = first_line
            next_command = lines[1] if len(lines) > 1 else "Continue with the task"
            
            # Remove 'await' keyword if present
            if 'await' in command_line:
                command_line = command_line.replace('await', '').strip()
            
            return command_line, next_command, False
            
        except Exception as e:
            logger.error(f"Error parsing response: {e}")
            return None, None, False
    
    @staticmethod
    def parse_javascript_response(response: str) -> tuple[Optional[Dict[str, Any]], Optional[str], bool]:
        """
        Parse JavaScript-based LLM response into command dict and next action.
        
        Args:
            response: Raw LLM response text with JSON command
            
        Returns:
            Tuple of (command_dict, next_action, is_completed)
        """
        try:
            lines = [line.strip() for line in response.split('\n') if line.strip()]
            
            if not lines:
                logger.warning("Empty response from LLM")
                return None, None, False
            
            # Parse JSON command from first line
            first_line = lines[0]
            
            # Try to extract JSON
            try:
                # Remove markdown code blocks if present
                if '```' in first_line:
                    first_line = first_line.replace('```json', '').replace('```', '').strip()
                
                command_dict = json.loads(first_line)
                
                # Check if completed
                if command_dict.get('action') == 'completed':
                    logger.info("Task marked as completed")
                    return command_dict, None, True
                
                # Get next action
                next_command = lines[1] if len(lines) > 1 else "Continue with the task"
                
                return command_dict, next_command, False
                
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse JSON command: {e}. Response: {first_line}")
                return None, None, False
            
        except Exception as e:
            logger.error(f"Error parsing JavaScript response: {e}")
            return None, None, False


class JavaScriptCommandExecutor:
    """Executes JSON-based JavaScript commands."""
    
    @staticmethod
    async def execute_command(page: Page, command_dict: Dict[str, Any], session: Optional['Session'] = None) -> bool:
        """
        Execute a JSON command using JavaScript.
        
        Args:
            page: The Playwright page object
            command_dict: Dictionary with action, selector, value, etc.
        
        Returns:
            True if successful, False otherwise
        """
        action = command_dict.get('action')
        
        try:
            if action == 'goto':
                url = command_dict.get('value', '')
                await page.goto(url)
                logger.info(f"Navigated to: {url}")
                return True
            
            elif action == 'click':
                selector = command_dict.get('selector', '')
                selector_type = command_dict.get('selector_type', 'css')
                open_in_new_tab = command_dict.get('open_in_new_tab', False)
                result = await JavaScriptExecutor.click_element(page, selector, selector_type, open_in_new_tab)
                if result:
                    logger.info(f"Clicked element: {selector} ({selector_type})")
                return result
            
            elif action == 'fill':
                selector = command_dict.get('selector', '')
                selector_type = command_dict.get('selector_type', 'css')
                value = command_dict.get('value', '')
                result = await JavaScriptExecutor.fill_input(page, selector, value, selector_type)
                if result:
                    logger.info(f"Filled {selector} with value ({selector_type})")
                return result
            
            elif action == 'select':
                # Select option in dropdown
                selector = command_dict.get('selector', '')
                selector_type = command_dict.get('selector_type', 'css')
                value = command_dict.get('value', '')
                result = await JavaScriptExecutor.select_dropdown(page, selector, value, selector_type)
                if result:
                    logger.info(f"Selected '{value}' in dropdown {selector} ({selector_type})")
                return result
            
            elif action == 'press_key':
                key = command_dict.get('value', 'Enter')
                result = await JavaScriptExecutor.press_key(page, key)
                if result:
                    logger.info(f"Pressed key: {key}")
                return result
            
            elif action == 'wait':
                timeout = command_dict.get('timeout', 2000)
                await page.wait_for_timeout(timeout)
                logger.info(f"Waited for {timeout}ms")
                return True
            
            elif action == 'wait_element':
                selector = command_dict.get('selector', '')
                selector_type = command_dict.get('selector_type', 'css')
                timeout = command_dict.get('timeout', 5000)
                result = await JavaScriptExecutor.wait_for_element(page, selector, selector_type, timeout)
                if result:
                    logger.info(f"Element found: {selector} ({selector_type})")
                else:
                    logger.warning(f"Element not found after {timeout}ms: {selector}")
                return result
            
            elif action == 'get_tabs':
                # Get list of all open tabs
                if session:
                    tabs = await TabManager.get_all_pages(session)
                    logger.info(f"Retrieved {len(tabs)} tabs")
                    return True
                return False
            
            elif action == 'switch_tab':
                # Switch to a specific tab
                tab_index = command_dict.get('tab_index', 0)
                if session:
                    result = await TabManager.switch_to_tab(session, tab_index)
                    if result:
                        logger.info(f"Switched to tab {tab_index}")
                    return result
                return False
            
            elif action == 'close_tab':
                # Close a specific tab or current tab
                tab_index = command_dict.get('tab_index')  # None = current tab
                if session:
                    result = await TabManager.close_tab(session, tab_index)
                    if result:
                        logger.info(f"Closed tab {tab_index if tab_index is not None else 'current'}")
                    return result
                return False
            
            elif action == 'close_other_tabs':
                # Close all tabs except current
                if session:
                    count = await TabManager.close_other_tabs(session)
                    logger.info(f"Closed {count} other tabs")
                    return True
                return False
            
            elif action == 'completed':
                logger.info("Task completed")
                return True
            
            else:
                logger.error(f"Unknown action: {action}")
                return False
                
        except Exception as e:
            logger.error(f"Error executing JavaScript command: {e}")
            return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events for the FastAPI app."""
    global _browser
    async with async_playwright() as playwright:
        _browser = await playwright.chromium.launch(
            headless=config.HEADLESS, 
            timeout=config.BROWSER_TIMEOUT
        )
        # Start session cleanup task
        cleanup_task = asyncio.create_task(session_manager.cleanup_expired_sessions())
        logger.info("Browser automation system started")
        yield
        # Cleanup
        cleanup_task.cancel()
        await _browser.close()
        logger.info("Browser automation system stopped")
    
app = FastAPI(lifespan=lifespan)

_browser = None



@app.post("/start_session", response_model=StartSessionResponse)
async def start_session(request: StartSessionRequest = StartSessionRequest()):
    """
    Creates a new browser session.
    
    Args:
        request: Session configuration with mode selection
    
    Returns:
        StartSessionResponse with session_id and metadata
    
    Example:
        curl --request POST \
        --url http://localhost:8000/start_session \
        --header 'content-type: application/json' \
        --data '{"mode":"interact"}'
    """
    try:
        session_id = session_manager.create_session()
        session = session_manager.get_session(session_id)
        
        if request.mode == ModeEnum.INTERACT:
            # Choose prompt based on configuration
            if config.USE_JAVASCRIPT_EXECUTION:
                session.llm = llm(JAVASCRIPT_INTERACT_PROMPT)
                session.use_javascript = True
                logger.info(f"Initialized LLM with JavaScript execution for session {session_id}")
            else:
                session.llm = llm(INTERACT_SYSTEM_PROMPT)
                session.use_javascript = False
                logger.info(f"Initialized LLM with Playwright commands for session {session_id}")
        
        return StartSessionResponse(
            session_id=session_id,
            mode=request.mode,
            created_at=session.created_at
        )
    except Exception as e:
        logger.error(f"Error creating session: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create session: {str(e)}")

@app.post("/interact/{session_id}", response_model=InteractResponse)
async def interact_command(session_id: str, request: InteractRequest):
    """
    Interacts with the browser session using natural language commands.
    
    Args:
        session_id: The unique session identifier from /start_session
        request: The interaction request with the command message
    
    Returns:
        InteractResponse with execution status and results
    
    Example:
        curl --request POST \
        --url http://localhost:8000/interact/371a5f22-63de-4df1-8754-b1e11f43141e \
        --header 'content-type: application/json' \
        --data '{"message":"log in into twitter.com with username <username> and password <password>"}'
    """
    start_time = time.time()
    
    # Validate session
    session = session_manager.get_session(session_id)
    if not session:
        logger.warning(f"Invalid session ID requested: {session_id}")
        raise HTTPException(
            status_code=404, 
            detail=f"Session {session_id} not found. Please create a session first."
        )
    
    # Initialize browser context and page if needed
    if not session.browser_context:
        try:
            session.browser_context = await _browser.new_context()
            logger.info(f"Created new browser context for session {session_id}")
        except Exception as e:
            logger.error(f"Failed to create browser context: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to create browser context: {str(e)}")
    
    if not session.page:
        try:
            session.page = await session.browser_context.new_page()
            session.all_pages.append(session.page)
            logger.info(f"Created new page for session {session_id}")
            
            # Listen for new pages (popups/new tabs) with deduplication
            def handle_popup(popup):
                # Check if this page is already tracked (prevent duplicates)
                if popup not in session.all_pages:
                    session.all_pages.append(popup)
                    logger.info(f"New tab/popup detected: {popup.url}")
                    
                    # Set up listener for when the page loads
                    async def on_load():
                        try:
                            await popup.wait_for_load_state('domcontentloaded', timeout=5000)
                            logger.info(f"Tab loaded: {popup.url}")
                        except Exception as e:
                            logger.debug(f"Tab load timeout: {e}")
                    
                    # Start load listener without blocking
                    asyncio.create_task(on_load())
            
            session.browser_context.on("page", handle_popup)
            
        except Exception as e:
            logger.error(f"Failed to create page: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to create browser page: {str(e)}")
    
    if not session.llm:
        logger.error(f"Session {session_id} has no LLM initialized")
        raise HTTPException(status_code=400, detail="Session not properly initialized with LLM")
    
    page = session.page
    user_message = request.message
    goal = user_message
    
    # Reset session state for new interaction
    session.action_done = False
    session.retry_count = 0
    
    logger.info(f"Starting interaction for session {session_id}: {user_message[:100]}...")
    
    while not session.action_done and session.retry_count < config.MAX_RETRIES:
        try:
            # Get LLM response
            response = session.llm.generate_response(user_message)
            logger.debug(f"LLM Response: {response}")
            
            # Parse and execute based on mode
            if session.use_javascript:
                # JavaScript execution mode
                command_dict, next_command, is_completed = ResponseParser.parse_javascript_response(response)
                
                if is_completed:
                    session.action_done = True
                    logger.info(f"Task completed for session {session_id}")
                    break
                
                if not command_dict:
                    logger.warning("No valid JSON command extracted from LLM response")
                    session.retry_count += 1
                    user_message = "No valid JSON command was generated. Please provide a valid JSON command in the format specified."
                    continue
                
                # Execute JavaScript command
                command_str = json.dumps(command_dict)
                session.last_command = command_str
                logger.info(f"Executing JavaScript command: {command_str}")
                
                success = await JavaScriptCommandExecutor.execute_command(page, command_dict, session)
                
                if not success:
                    raise Exception(f"JavaScript command execution failed: {command_dict.get('action')}")
                
                session.commands_executed.append(command_str)
                
            else:
                # Playwright execution mode
                command_line, next_command, is_completed = ResponseParser.parse_response(response)
                
                if is_completed:
                    session.action_done = True
                    logger.info(f"Task completed for session {session_id}")
                    break
                
                if not command_line:
                    logger.warning("No command extracted from LLM response")
                    session.retry_count += 1
                    user_message = "No valid command was generated. Please provide a valid Playwright command."
                    continue
                
                # Execute Playwright command
                session.last_command = command_line
                logger.info(f"Executing Playwright command: {command_line}")
                
                await CommandExecutor.execute(page, command_line)
                session.commands_executed.append(command_line)
            
            # Get tab information
            tab_info = ""
            try:
                tabs = await TabManager.get_all_pages(session)
                if tabs and len(tabs) > 1:
                    tab_info = f"\n\n**Open Tabs ({len(tabs)} total)**\n"
                    for tab in tabs:
                        current_marker = " ← CURRENT TAB" if tab['is_current'] else ""
                        tab_info += f"[Tab {tab['index']}] {tab['title']} - {tab['url'][:80]}{current_marker}\n"
            except Exception as e:
                logger.warning(f"Failed to get tab info: {e}")
            
            # Get detailed page elements
            try:
                page_elements = await DOMInspector.get_page_elements(page)
                session.page_snapshot = page_elements
            except Exception as e:
                logger.warning(f"Failed to get page elements: {e}")
                session.page_snapshot = "Failed to extract page elements."
            
            # Build next user message with actual page structure
            user_message = f"**Final Goal**\n{goal}"
            user_message += tab_info  # Add tab info if multiple tabs
            user_message += f"\n\n**Current Page Elements**\n{session.page_snapshot[:3000]}"  # Increased limit for element list
            user_message += f"\n\n**Next Goal**\n{next_command}"      
            user_message += f"\n\n**Commands Executed (last 5)**\n" + "\n".join(session.commands_executed[-5:])  # Last 5 commands
            
            session.retry_count = 0
            
        except Exception as e:
            session.retry_count += 1
            error_msg = str(e)
            logger.error(f"Error executing command (attempt {session.retry_count}/{config.MAX_RETRIES}): {error_msg}")
            
            if session.retry_count >= config.MAX_RETRIES:
                execution_time = time.time() - start_time
                return InteractResponse(
                    status="failure",
                    session_id=session_id,
                    commands_executed=session.commands_executed,
                    error=f"Max retries reached. Last error: {error_msg}",
                    code=500,
                    execution_time_seconds=round(execution_time, 2)
                )
            
            # Build retry message
            mode_str = "JSON command" if session.use_javascript else "Playwright command"
            user_message = f"The {mode_str} '{session.last_command}' failed with error: {error_msg}. Please try a different approach."
            user_message += f"\n\n**Current Page Elements**\n{session.page_snapshot[:3000]}"
            user_message += f"\n\n**Commands Executed (last 5)**\n" + "\n".join(session.commands_executed[-5:])

        # Check if max retries reached
        if session.retry_count >= config.MAX_RETRIES:
            execution_time = time.time() - start_time
            return InteractResponse(
                status="failure",
                session_id=session_id,
                commands_executed=session.commands_executed,
                error="Max retries reached",
                code=500,
                execution_time_seconds=round(execution_time, 2)
            )

        if session.action_done:
            break
        
        # Wait before next iteration
        await page.wait_for_timeout(config.PAGE_WAIT_TIMEOUT)
    
    execution_time = time.time() - start_time
    logger.info(f"Interaction completed for session {session_id} in {execution_time:.2f}s")
    
    return InteractResponse(
        status="success",
        session_id=session_id,
        commands_executed=session.commands_executed,
        code=200,
        execution_time_seconds=round(execution_time, 2)
    )

@app.get("/session/{session_id}/status", response_model=SessionStatusResponse)
async def get_session_status(session_id: str):
    """
    Get the status of a specific session.
    
    Args:
        session_id: The unique session identifier
    
    Returns:
        SessionStatusResponse with session details
    """
    session = session_manager.get_session(session_id)
    
    if not session:
        return SessionStatusResponse(
            session_id=session_id,
            exists=False,
            active=False,
            commands_executed_count=0
        )
    
    return SessionStatusResponse(
        session_id=session_id,
        exists=True,
        active=session.page is not None,
        commands_executed_count=len(session.commands_executed),
        created_at=session.created_at,
        last_activity=session.last_activity
    )


@app.delete("/session/{session_id}")
async def close_session(session_id: str):
    """
    Close and cleanup a specific session.
    
    Args:
        session_id: The unique session identifier
    
    Returns:
        Success message
    """
    session = session_manager.get_session(session_id)
    
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    
    await session_manager.close_session(session_id)
    logger.info(f"Session {session_id} closed via API")
    
    return {
        "status": "success",
        "message": f"Session {session_id} has been closed",
        "code": 200
    }


@app.get("/sessions")
async def list_sessions():
    """
    List all active sessions.
    
    Returns:
        List of session IDs and their basic info
    """
    sessions_info = []
    
    for session_id, session in session_manager.sessions.items():
        sessions_info.append({
            "session_id": session_id,
            "active": session.page is not None,
            "commands_executed": len(session.commands_executed),
            "created_at": session.created_at.isoformat(),
            "last_activity": session.last_activity.isoformat()
        })
    
    return {
        "total_sessions": len(sessions_info),
        "sessions": sessions_info
    }


@app.get("/health")
async def health_check():
    """
    Health check endpoint.
    
    Returns:
        System health status
    """
    return {
        "status": "healthy",
        "browser_active": _browser is not None,
        "active_sessions": len(session_manager.sessions),
        "timestamp": datetime.now().isoformat()
    }


if __name__ == "__main__":
    # Ensure logs directory exists
    import os
    os.makedirs('logs', exist_ok=True)
    
    logger.info(f"Starting server on {config.HOST}:{config.PORT}")
    uvicorn.run(
        app, 
        host=config.HOST, 
        port=config.PORT,
        log_level="info"
    )
