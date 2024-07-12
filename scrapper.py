import contextlib
import logging
import os
import time
from secrets import SystemRandom
from typing import Dict, List

import seleniumwire.undetected_chromedriver as webdriver
from bs4 import BeautifulSoup, Tag
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    ElementNotInteractableException,
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.webdriver import WebDriver
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC  # noqa: N812
from selenium.webdriver.support.ui import WebDriverWait

logger = logging.getLogger(__name__)


class WebDriverManager:
    def __init__(self, proxy_url: str):
        selenium_options = {
            "proxy": {
                "http": proxy_url,
            }
        }

        self.driver = webdriver.Chrome(
            options=self._init_options(),
            seleniumwire_options=selenium_options,
            version_main=112,
            driver_executable_path="/usr/lib/chromium/chromedriver",
        )

        self.driver.implicitly_wait(4)
        self.proxy = proxy_url
        self.proxy_ip = proxy_url.split("@")[-1].split(":")[0]

    def __enter__(self) -> WebDriver:
        st = self.driver.execute_script("return navigator.webdriver")
        assert not st
        return self.driver

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.driver.quit()

    def _init_options(self) -> Options:
        options = Options()
        options.add_argument("--headless")
        options.add_argument("--disable-gpu")
        options.add_argument("--np-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--ignore-ssl-errors=yes")
        options.add_argument("--ignore-certificate-errors")
        options.add_argument("--blink-settings=imagesEnabled=false")
        options.add_argument("--disable-notifications")
        return options


class Scrapper:
    at_least_wait = 5
    default_time = 3
    cookie = "Decline optional cookies"
    login_msg = "You must log in to continue."

    def __init__(self) -> None:
        self.rand_generator = SystemRandom()

    def get_new_posts(self, account) -> Dict[str, List]:
        new_posts: Dict[str, List] = {}

        with WebDriverManager(account.proxy_url) as driver:
            self.handle_authorization(account, driver)

            for group in account.groups:
                posts: List[Tag] = self.get_feed_posts(driver, group, 8)
                new_posts[group.group_link] = self.get_new_posts_from_recent([post for post in posts], group)

        return new_posts

    def get_feed_posts(self, driver: WebDriver, group, at_least_posts: int) -> List:
        self.load_group_page(driver, group)
        driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)

        scroll_position = 1
        recent_leads: List = []

        while True:
            driver.execute_script(f"window.scrollTo(0, {scroll_position} * document.body.scrollHeight/6);")
            self.wait(4, 1)

            see_original = driver.find_elements(By.XPATH, "//div[text()='See original' and @role='button']")
            for el in see_original:
                with contextlib.suppress(
                        StaleElementReferenceException, ElementClickInterceptedException, TimeoutException
                ):
                    WebDriverWait(driver, 5).until(EC.element_to_be_clickable(el)).click()

            see_more = driver.find_elements(By.XPATH, "//div[text()='See more' and @role='button']")
            for el in see_more:
                with contextlib.suppress(
                        StaleElementReferenceException, ElementClickInterceptedException, TimeoutException
                ):
                    WebDriverWait(driver, 5).until(EC.element_to_be_clickable(el)).click()

            post_links = driver.find_elements(By.XPATH, "//a[@href='#']")
            for post_link in post_links:
                with contextlib.suppress(ElementNotInteractableException, StaleElementReferenceException):
                    ActionChains(driver).move_to_element(post_link).perform()

            soup = BeautifulSoup(driver.page_source, "html.parser")

            recent_leads += [
                self.get_lead_from_feed_post(post)
                for post in soup.find("div", {"role": "feed"}).find_all("div", {"role": "article"})
                if self._is_valid_post(post)
            ]
            recent_leads = list(set([lead for lead in recent_leads if lead.user_link and lead.post_link]))

            if len(recent_leads) >= at_least_posts:
                return recent_leads
            else:
                scroll_position += 1

    def wait(self, at_least_wait: int = 5, default_time: int = 3) -> None:
        time.sleep(at_least_wait + default_time * self.rand_generator.random())

    def get_lead_from_feed_post(self, feed_post: Tag):
        user_link: str | None = None
        post_text: str | None = None
        post_link: str | None = None

        post_info = self._get_post_info(feed_post)

        if not post_info:
            return {"post_text": post_text, "user_link": user_link, "post_link": post_link}

        user_info = self._get_user_info(post_info)

        user_link = self._get_user_link(user_info)
        post_link = self._get_post_link(user_info)
        post_text = self._get_post_text(post_info)

        return {"post_text": post_text, "user_link": user_link, "post_link": post_link}

    def handle_authorization(self, user, driver: WebDriver) -> None:
        driver.get(settings.FB_MAIN_LINK)

        if user.cookies:
            self.add_cookie(user.cookies, driver)

        self.wait()

        if new_cookies := self.handle_login(user, driver):
            logger.warning(f"Cookies were updated for {user.username}")
            user.new_cookies = new_cookies

            self.add_cookie(user.new_cookies, driver)

    def add_cookie(self, cookies: list[dict], driver: WebDriver) -> None:
        for cookie in cookies:
            if cookie["sameSite"] in ["unspecified", "no_restriction"]:
                cookie["sameSite"] = "Lax"

            if cookie["sameSite"] == "lax":
                cookie["sameSite"] = "Lax"

            driver.add_cookie(cookie)

    def handle_login(self, user, driver: WebDriver) -> list[dict] | None:
        with contextlib.suppress(NoSuchElementException):
            driver.find_element(By.XPATH, f"//button[@title='{self.cookie}']").click()

        with contextlib.suppress(NoSuchElementException):
            driver.find_element(By.XPATH, f"//div[text()='{self.login_msg}']")

            driver.find_element(By.ID, "email").send_keys(user.username)
            self.wait()
            driver.find_element(By.ID, "pass").send_keys(user.password)
            self.wait()

            driver.find_element(By.ID, "loginbutton").click()
            self.wait()

            return driver.get_cookies()

    def load_group_page(self, driver: WebDriver, group) -> None:
        while True:
            driver.get(group.group_link)
            self.wait()
            assert driver.current_url == group.group_link

            if driver.find_element(By.XPATH, "//div[@role='feed']"):
                break

    def get_new_posts_from_recent(self, recent: list, group) -> list:
        last_lead_index = [
            index for index, post in enumerate(recent) if post.post_link and post.post_link == group.last_post_link
        ]
        return recent[: last_lead_index[0]] if last_lead_index else recent

    def _get_post_info(self, feed_post: Tag) -> list[Tag] | None:
        while True:
            try:
                if not feed_post["style"]:
                    feed_post = feed_post.contents[0]
                    continue
                if "aria-hidden" in feed_post.attrs:
                    break
                for div in feed_post.contents[0].contents:
                    if "class" not in div.attrs and div.contents:
                        return div.contents[0].contents[0].contents[1:]

            except KeyError:
                try:
                    feed_post = feed_post.contents[0]
                except IndexError:
                    break

    def _get_user_info(self, post_info: list[Tag]) -> Tag:
        return post_info[0].contents[0].contents[1]

    def _get_post_link(self, user_info: Tag) -> str:
        post_link = user_info.contents[0].contents[1].find("a")["href"]
        return post_link[: post_link.find("?__cft__[0]")]

    def _get_user_link(self, user_info: Tag) -> str:
        user_link = user_info.find("a")["href"]
        return user_link[: user_link.find("?__cft__[0]")]

    def _get_post_text(self, post_info: list[Tag]) -> str:
        post_text = ""
        for el in post_info[1].contents:
            if "data-ad-comet-preview" in el.contents[0].attrs:
                post_text += el.contents[0].contents[0].text + "\n"
            elif el.name == "blockquote":
                post_text += "Translated text: " + el.contents[0].contents[0].text
            elif len(el.contents[0].contents[0].contents) == 3:
                if el.contents[0].contents[0].name == "a":
                    continue
                else:
                    try:
                        post_text += el.contents[0].contents[0].contents[-1].contents[0].text + "\n"
                    except IndexError:
                        post_text += "Inserted message doesn't contain any text\n"
            elif len(el.contents[0].contents) == 3:
                if el.find("div", {"data-ad-comet-preview": "message"}):
                    post_text += el.find("div", {"data-ad-comet-preview": "message"}).text
                else:
                    logger.warning(f"Undetected text in post: {self._get_post_link(self._get_user_info(post_info))}")
            elif set(("class", "id")) == set(el.attrs.keys()):
                continue
            else:
                post_text += el.text + "\n"
        return post_text if post_text else "No text available"

    def _is_valid_post(self, post: Tag) -> bool:
        return (
                "class" in post.attrs
                and post.contents
                and "hidden" not in post.contents[0].contents[0].attrs
                and "aria-posinset" in post.attrs
        )

    def click_all_allow_cookies_buttons(self):
        try:
            logger.info('Starting to look for cookie consent buttons...')
            WebDriverWait(self.driver, 10).until(
                EC.visibility_of_any_elements_located((By.XPATH, "//div[@aria-label='Allow all cookies']"))
            )
            all_buttons = self.driver.find_elements(By.XPATH, "//div[@aria-label='Allow all cookies']")
            logger.info(f"Found {len(all_buttons)} buttons with aria-label 'Allow all cookies'")
            for button in all_buttons:
                if button.is_displayed() and button.is_enabled():
                    button.click()
                    logger.info("Clicked a cookie button.")
                    # Wait to ensure the modal disappears after clicking
                    WebDriverWait(self.driver, 5).until(
                        EC.invisibility_of_element((By.XPATH, "//div[@aria-label='Allow all cookies']"))
                    )
                    logger.info("Cookie consent modal has disappeared.")
                    break  # Exit after successfully clicking one button
        except Exception as e:
            logger.error("Failed to handle cookie consent properly.", exc_info=e)
