from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as ec

from vpa.forex_auto.base_page import BasePage


class ForexPage(BasePage):
    __url = "https://forexsb.com/historical-forex-data"
    __load_button = (By.XPATH, "/html//button[@id='btn-load-data']")
    __forex_data_download = (By.LINK_TEXT, "GBPUSD_D1.csv")
    __body_element = (By.XPATH, "//body")

    def __init__(self, driver: WebDriver):
        super().__init__(driver)

    def open(self):
        super()._open_url(self.__url)
        super()._click(self.__body_element)




    def load_data(self):
        super()._click(self.__load_button)

    def download_data(self):
        super()._click(self.__forex_data_download)
