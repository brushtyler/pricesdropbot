#!/usr/bin/env python3

import platform
import subprocess

import selenium
from selenium.webdriver.common.by import By
from time import sleep
import threading
import os
import pickle
from selenium.common.exceptions import NoSuchElementException
from datetime import datetime
import sys

def log(message):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}] {message}")

class pricesdrop_bot(threading.Thread):
    def __init__(self,amazon_host,amazon_tag,amazon_email,amazon_psw,asin,cut_price,autocheckout,object_state=None):
        self.amazon_host=amazon_host
        self.amazon_tag=amazon_tag
        self.amazon_email=amazon_email
        self.amazon_psw=amazon_psw
        self.asin=asin
        self.cut_price=cut_price
        self.autocheckout=autocheckout
        self.object_state = [state.lower() for state in object_state] if object_state else []
        self.previous_main_price = 0.0
        self.previous_offer_prices = []
        self.previous_offer_count = -1
        threading.Thread.__init__(self) 

    def send_notification(self, title, message):
        if platform.system() == "Linux":
            try:
                # Check if notify-send is available
                subprocess.run(["notify-send", "--version"], check=True, capture_output=True)
                subprocess.run(["notify-send", title, message])
            except FileNotFoundError:
                log(f"Notification: {title} - {message} (notify-send not found, falling back to print)")
            except Exception as e:
                exc_type, exc_value, exc_tb = sys.exc_info()
                file_name = exc_tb.tb_frame.f_code.co_filename
                line_number = exc_tb.tb_lineno
                log(f"Error sending notification: {e} at file {file_name} line {line_number}, falling back to print")
                log(f"Notification: {title} - {message}")
        else:
            log(f"Notification: {title} - {message}")

    def run(self):
        options = selenium.webdriver.ChromeOptions() 
        options.headless = False

        # Configure the undetected_chromedriver options
        driver = selenium.webdriver.Chrome(options=options) 

        if os.path.exists(".cookies.pkl"):
            driver.get(f"https://{self.amazon_host}/")
            with open(".cookies.pkl", "rb") as f:
                cookies = pickle.load(f)
                for cookie in cookies:
                    if 'domain' in cookie:
                        del cookie['domain']
                    driver.add_cookie(cookie)
            driver.refresh()
        else:
            driver.get(f"https://{self.amazon_host}/ap/signin?openid.pape.max_auth_age=0&openid.return_to=https%3A%2F%2F{self.amazon_host}%2Fgp%2Fcart%2Fview.html%2Fref%3Dnav_ya_signin%3F&openid.identity=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0%2Fidentifier_select&openid.assoc_handle=itflex&openid.mode=checkid_setup&openid.claimed_id=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0%2Fidentifier_select&openid.ns=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0")
            sleep(1)
            driver.find_element(by=By.XPATH, value='//*[@id="ap_email"]').send_keys(self.amazon_email)
            sleep(1)
            driver.find_element(by=By.XPATH, value='//*[@id="continue"]').click()
            sleep(1)
            driver.find_element(by=By.XPATH, value='//*[@id="ap_password"]').send_keys(self.amazon_psw)
            sleep(1)
            driver.find_element(by=By.XPATH, value='//*[@id="signInSubmit"]').click()

            input("Once 2FA step is completed (if any), press Enter to continue...") # Wait for 2FA

            # Save cookies to avoid always performing login+2FA
            with open(".cookies.pkl", "wb") as f:
                pickle.dump(driver.get_cookies(), f)

        check = True
        while check:
            sleep(2)
            try:
                driver.get(f"https://{self.amazon_host}/dp/{self.asin}/ref=olp-opf-redir?aod=1{f'&tag={self.amazon_tag}' if self.amazon_tag else ''}")
                sleep(3)

                # Check the main "Brand New" option (Featured Offer)
                try:
                    main_offer_container = driver.find_element(by=By.XPATH, value="//div[@id='newAccordionRow_0']")
                    price_whole_str = main_offer_container.find_element(by=By.XPATH, value=".//span[contains(@class, 'a-price-whole')]").text.replace('.', '').replace(',', '')
                    try:
                        price_fraction_str = main_offer_container.find_element(by=By.XPATH, value=".//span[contains(@class, 'a-price-fraction')]").text
                        main_current_price = float(f"{price_whole_str}.{price_fraction_str}")
                    except NoSuchElementException:
                        main_current_price = float(price_whole_str)

                    price_changed = main_current_price != self.previous_main_price
                    if price_changed:
                        self.previous_main_price = main_current_price

                    condition_text = "Nuovo" # Assume "Nuovo" (New) if not specified, common for main offer
                    try:
                        condition_span = main_offer_container.find_element(by=By.XPATH, value=".//span[contains(@class, 'offer-display-feature-text-message')]")
                        condition_text = condition_span.text.strip()
                    except NoSuchElementException:
                        pass # Keep default "Nuovo"

                    normalized_state = "new" if "nuovo" in condition_text.lower() else "used"
                    
                    log_message = f"Main offer state: '{condition_text}' (normalized: '{normalized_state}'), price: {main_current_price:.2f}"

                    if self.object_state and normalized_state not in self.object_state:
                        if price_changed:
                            log(f"{log_message} - SKIPPING: State not in desired list {self.object_state}")
                    elif main_current_price <= self.cut_price:
                        if price_changed:
                            log(f"Price drop detected for main offer at: {main_current_price:.2f}")
                        
                        log(f"{log_message} - ACCEPTED: Price is low enough.")
                        main_add_to_cart_button = main_offer_container.find_element(by=By.XPATH, value=".//input[@id='add-to-cart-button']")
                        main_add_to_cart_button.click()
                        self.send_notification("Amazon Autobuy Bot", f"Item {self.asin} added to cart at {main_current_price:.2f}!")
                        
                        sleep(0.5)
                        driver.find_element(by=By.XPATH, value='//*[@id="sc-buy-box-ptc-button"]/span/input').click()
                        if self.autocheckout == True:
                            driver.find_element(by=By.XPATH, value='//*[@id="a-autoid-0-announce"]').click()
                            driver.find_element(by=By.XPATH, value='//*[@id="submitOrderButtonId"]/span/input').click()
                        
                        check = False
                    else:
                        if price_changed:
                            log(f"{log_message} - SKIPPING: The current price is not low enough: {main_current_price:.2f}")
                except NoSuchElementException as e:
                    exc_type, exc_value, exc_tb = sys.exc_info()
                    file_name = exc_tb.tb_frame.f_code.co_filename
                    line_number = exc_tb.tb_lineno
                    error_message = f"File: {file_name}, Line: {line_number}, Error: {e}"
                    logs_dir = "logs"
                    if not os.path.exists(logs_dir):
                        os.makedirs(logs_dir)
                    html_file_name = os.path.join(logs_dir, f"debug_main_offer_not_found_{self.asin}.html")
                    with open(html_file_name, "w", encoding="utf-8") as f:
                        f.write(f"<!-- {error_message} -->\n")
                        f.write(driver.page_source)
                    log(f"Main offer (newAccordionRow_0) not found. Page HTML saved to {html_file_name} for debugging. {error_message}")
                except Exception as e:
                    exc_type, exc_value, exc_tb = sys.exc_info()
                    file_name = exc_tb.tb_frame.f_code.co_filename
                    line_number = exc_tb.tb_lineno
                    log(f"An unexpected error occurred while processing the main offer: {e} at file {file_name} line {line_number}")

                if not check: # If main offer was processed and bought, exit
                    break

                offer_containers = driver.find_elements(by=By.XPATH, value="//div[contains(@class, 'aod-information-block') and @role='listitem' and .//input[@name='submit.addToCart']]")
                current_offer_count = len(offer_containers)
                if current_offer_count != self.previous_offer_count:
                    log(f"{current_offer_count} other offers found")
                    self.previous_offer_count = current_offer_count

                if not offer_containers:
                    driver.refresh()
                    sleep(2)
                    continue

                new_offer_prices = []
                for i, offer in enumerate(offer_containers):
                    try:
                        price_changed = False # Default to false
                        
                        condition_text = "N/A"
                        try:
                            condition_heading = offer.find_element(by=By.XPATH, value=".//div[contains(@id, 'aod-offer-heading')]//h5")
                            condition_text = condition_heading.text.strip()
                        except NoSuchElementException:
                            log("Could not find condition for an offer, skipping.")
                            continue
                        
                        normalized_state = "unknown"
                        condition_lower = condition_text.lower()
                        if "nuovo" in condition_lower:
                            normalized_state = "new"
                        elif "usato - come nuovo" in condition_lower:
                            normalized_state = "used-like new"
                        elif "usato - ottime condizioni" in condition_lower:
                            normalized_state = "used-very good"
                        elif "usato - buone condizioni" in condition_lower:
                            normalized_state = "used-good"
                        elif "usato - condizioni accettabili" in condition_lower:
                            normalized_state = "used-acceptable"
                        elif "usato" in condition_lower:
                            normalized_state = "used"

                        price_whole_str = offer.find_element(by=By.XPATH, value=".//span[contains(@class, 'a-price-whole')]").text.replace('.', '').replace(',', '')
                        try:
                            price_fraction_str = offer.find_element(by=By.XPATH, value=".//span[contains(@class, 'a-price-fraction')]").text
                            current_price = float(f"{price_whole_str}.{price_fraction_str}")
                        except NoSuchElementException:
                            current_price = float(price_whole_str)
                        
                        new_offer_prices.append(current_price)

                        if i >= len(self.previous_offer_prices) or self.previous_offer_prices[i] != current_price:
                            price_changed = True

                        log_message = f"Found offer: State='{condition_text}' (normalized='{normalized_state}'), Price={current_price:.2f}"

                        if self.object_state and normalized_state not in self.object_state:
                            if price_changed:
                                log(f"{log_message} - SKIPPING: State not in desired list {self.object_state}")
                            continue

                        if current_price <= self.cut_price:
                            if price_changed:
                                log(f"Price drop detected at: {current_price:.2f}")
                            
                            log(f"{log_message} - ACCEPTED: Price is low enough.")
                            add_to_cart_button = offer.find_element(by=By.XPATH, value=".//input[@name='submit.addToCart']")
                            add_to_cart_button.click()
                            self.send_notification("Amazon Autobuy Bot", f"Item {self.asin} added to cart at {current_price:.2f}!")
                            
                            sleep(0.5)
                            driver.find_element(by=By.XPATH, value='//*[@id="sc-buy-box-ptc-button"]/span/input').click()
                            if self.autocheckout == True:
                                driver.find_element(by=By.XPATH, value='//*[@id="a-autoid-0-announce"]').click()
                                driver.find_element(by=By.XPATH, value='//*[@id="submitOrderButtonId"]/span/input').click()
                            
                            check = False
                            break
                        else:
                            if price_changed:
                                log(f"{log_message} - SKIPPING: Price is not low enough.")
                    except Exception as e:
                        exc_type, exc_value, exc_tb = sys.exc_info()
                        file_name = exc_tb.tb_frame.f_code.co_filename
                        line_number = exc_tb.tb_lineno
                        error_message = f"File: {file_name}, Line: {line_number}, Error: {e}"
                        
                        logs_dir = "logs"
                        if not os.path.exists(logs_dir):
                            os.makedirs(logs_dir)
                        html_file_name = os.path.join(logs_dir, f"debug_other_offer_not_found_{self.asin}.html")
                        with open(html_file_name, "w", encoding="utf-8") as f:
                            f.write(f"<!-- {error_message} -->\n")
                            f.write(driver.page_source)
                        log(f"Error processing an offer. Page HTML saved to {html_file_name} for debugging. {error_message}")

                self.previous_offer_prices = new_offer_prices
                
                if not check: # If one of the other offers was processed and bought, exit
                    break

            except Exception as e:
                exc_type, exc_value, exc_tb = sys.exc_info()
                file_name = exc_tb.tb_frame.f_code.co_filename
                line_number = exc_tb.tb_lineno
                log(f"Error finding offers: {e} at file {file_name} line {line_number}")
                driver.refresh()
                sleep(2)
            

        driver.quit()
    
        


amazon_host=os.getenv("AMAZON_HOST") or "www.amazon.it"
amazon_tag=os.getenv("AMAZON_TAG") or None

amazon_email=os.getenv("AMAZON_EMAIL")
amazon_psw=os.getenv("AMAZON_PASSWORD")

products = [
  # Example: Look for a new item under 50.00
  #{ "asin": "B0DTKCCFMK", "cut_price": 50.00, "autocheckout": False, "object_state": ["new"] },
  # Example: Look for a used item (like new or very good) under 800.00
  #{ "asin": "B0CZXNNJW8", "cut_price": 800.00, "autocheckout": False, "object_state": ["used-like new", "used-very good"] },
  # Example: Look for any state under 25.00 (if object_state is not provided)
  # { "asin": "B08P3V52P3", "cut_price": 25.00, "autocheckout": False },
]

threads_list=[]

for item in products:
    log(f"Start looking for price drop on product {item['asin']}: {('buy it' if item['autocheckout'] else 'add it to cart')} if price drops under {item['cut_price']:.2f}...")
    t=pricesdrop_bot(amazon_host=amazon_host, amazon_tag=amazon_tag, amazon_email=amazon_email, amazon_psw=amazon_psw, asin=item["asin"], cut_price=item["cut_price"], autocheckout=item["autocheckout"], object_state=item["object_state"])
    t.start() 
    threads_list.append(t) 
  
for t in threads_list: 
    t.join()
