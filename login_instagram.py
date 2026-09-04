from playwright.sync_api import sync_playwright

STORAGE_STATE_FILE = "instagram_state.json"
VIEWPORT = {"width": 1200, "height": 900}
START_URL = "https://www.instagram.com/"


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(viewport=VIEWPORT)
        page = context.new_page()
        page.goto(START_URL)
        input(
            "브라우저 창에서 인스타그램에 로그인한 뒤, "
            "이 터미널로 돌아와 Enter를 누르세요..."
        )
        context.storage_state(path=STORAGE_STATE_FILE)
        browser.close()
        print(f"로그인 세션을 저장했습니다: {STORAGE_STATE_FILE}")


if __name__ == "__main__":
    main()
