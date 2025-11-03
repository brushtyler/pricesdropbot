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
import toml
import random
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from dotenv import load_dotenv

load_dotenv()

def log(message, product_name=None):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}]{f' [{product_name}]' if product_name else ''} {message}")

# States for adding a product
ASK_ASIN, ASK_NAME, ASK_CUT_PRICE, ASK_AUTOCHECKOUT = range(4)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hello! I am your Prices Drop Bot. Use /add to add a product or /delete to remove one.")

async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Please send me the ASIN of the product you want to add.")
    return ASK_ASIN

async def add_asin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['asin'] = update.message.text
    await update.message.reply_text("Please send me the name of the product.")
    return ASK_NAME

async def add_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['name'] = update.message.text
    await update.message.reply_text("Please send me the cut price (e.g., 100.50).")
    return ASK_CUT_PRICE

async def add_cut_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data['cut_price'] = float(update.message.text)
        await update.message.reply_text("Do you want to enable autocheckout for this product? (yes/no)")
        return ASK_AUTOCHECKOUT
    except ValueError:
        await update.message.reply_text("Invalid price. Please enter a number (e.g., 100.50).")
        return ASK_CUT_PRICE

async def add_autocheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    autocheckout_str = update.message.text.lower()
    context.user_data['autocheckout'] = autocheckout_str == 'yes'

    product_data = {
        "name": context.user_data['name'],
        "asin": context.user_data['asin'],
        "cut_price": context.user_data['cut_price'],
        "autocheckout": context.user_data['autocheckout']
    }

    # Update products.toml
    products_file = 'products.toml'
    try:
        with open(products_file, 'r', encoding='utf-8') as f:
            products_toml = toml.load(f)
    except FileNotFoundError:
        products_toml = {}

    products_toml[product_data['name']] = {
        "asin": product_data['asin'],
        "cut_price": product_data['cut_price'],
        "autocheckout": product_data['autocheckout']
    }

    with open(products_file, 'w', encoding='utf-8') as f:
        toml.dump(products_toml, f)

    # Start monitoring the new product
    start_monitoring_product(product_data)

    await update.message.reply_text(f"Product '{product_data['name']}' added and monitoring started!")
    return ConversationHandler.END

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Operation cancelled.")
    return ConversationHandler.END

async def delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Please provide the ASIN of the product to delete. Usage: /delete <ASIN>")
        return
    asin_to_delete = context.args[0]

    # Stop monitoring the product
    stop_monitoring_product(asin_to_delete)

    # Remove from products.toml
    products_file = 'products.toml'
    try:
        with open(products_file, 'r', encoding='utf-8') as f:
            products_toml = toml.load(f)
    except FileNotFoundError:
        products_toml = {}

    product_name_to_delete = None
    for name, details in products_toml.items():
        if details.get('asin') == asin_to_delete:
            product_name_to_delete = name
            break

    if product_name_to_delete:
        del products_toml[product_name_to_delete]
        with open(products_file, 'w', encoding='utf-8') as f:
            toml.dump(products_toml, f)
        await update.message.reply_text(f"Product with ASIN {asin_to_delete} deleted and monitoring stopped.")
    else:
        await update.message.reply_text(f"Product with ASIN {asin_to_delete} not found in the monitoring list.")

async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not active_threads:
        await update.message.reply_text("No products are currently being monitored.")
        return

    message = "Currently monitored products:\n"
    for asin, thread_info in active_threads.items():
        product_name = thread_info['thread'].product_name
        cut_price = thread_info['thread'].cut_price
        autocheckout = thread_info['thread'].autocheckout
        message += f"- <b>{product_name}</b> (ASIN: {asin}, Cut Price: {cut_price:.2f}, Autocheckout: {autocheckout})\n"
    await update.message.reply_text(message, parse_mode="HTML")

def telegram_bot_main():
    application = Application.builder().token(os.getenv("TELEGRAM_BOT_TOKEN")).build()

    # Handlers
    application.add_handler(CommandHandler("start", start_command))

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("add", add_command)],
        states={
            ASK_ASIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_asin)],
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_name)],
            ASK_CUT_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_cut_price)],
            ASK_AUTOCHECKOUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_autocheckout)],
        },
        fallbacks=[CommandHandler("cancel", cancel_command)],
    )
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("delete", delete_command))
    application.add_handler(CommandHandler("list", list_command))

    log("Telegram bot started polling...")
    application.run_polling()

def send_telegram_notification(message, product_name=None):
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if bot_token and chat_id:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML"
        }
        try:
            response = requests.post(url, json=payload)
            if response.status_code == 200:
                log("Telegram notification sent successfully.", product_name)
            else:
                log(f"Failed to send Telegram notification. Status code: {response.status_code}, Response: {response.text}", product_name)
        except Exception as e:
            log(f"An error occurred while sending Telegram notification: {e}", product_name)
    else:
        log("Telegram bot token or chat ID not configured. Skipping notification.", product_name)


class pricesdrop_bot(threading.Thread):
    def __init__(self,amazon_host,amazon_tag,amazon_email,amazon_psw,product, stop_event):
        self.amazon_host=amazon_host
        self.amazon_tag=amazon_tag
        self.amazon_email=amazon_email
        self.amazon_psw=amazon_psw
        self.product_name=product["name"]
        self.asin=product["asin"]
        self.cut_price=product["cut_price"]
        self.autocheckout=product.get("autocheckout", False)
        object_state=product.get("object_state")
        self.object_state = [state.lower() for state in object_state] if object_state else []
        self.previous_main_price = 0.0
        self.previous_offer_prices = []
        self.previous_main_offer_xpath = None
        self.stop_event = stop_event
        threading.Thread.__init__(self) 

    def _save_debug_html(self, driver, exception, context_name):
        exc_type, exc_value, exc_tb = sys.exc_info()
        file_name = exc_tb.tb_frame.f_code.co_filename
        line_number = exc_tb.tb_lineno
        current_url = driver.current_url
        error_message = f"URL: {current_url}, File: {file_name}, Line: {line_number}, Error: {exception}"
        
        logs_dir = "logs"
        if not os.path.exists(logs_dir):
            os.makedirs(logs_dir)
            
        safe_product_name = self.product_name.replace(' ', '_')
        html_file_name = os.path.join(logs_dir, f"debug_{context_name}_not_found_{safe_product_name}_{self.asin}.html")
        
        with open(html_file_name, "w", encoding="utf-8") as f:
            f.write(f"<!-- {error_message} -->\n")
            f.write(driver.page_source)
            
        log(f"Error during '{context_name}' processing. Page HTML saved to {html_file_name} for debugging. {error_message}", self.product_name)

    def _find_element_by_multiple_xpaths(self, driver, xpaths, description="element", xpath_tracker_attribute_name=None):
        for xpath in xpaths:
            try:
                element = driver.find_element(by=By.XPATH, value=xpath)
                
                if xpath_tracker_attribute_name:
                    previous_xpath = getattr(self, xpath_tracker_attribute_name, None)
                    if xpath != previous_xpath:
                        log(f"Found {description} using new XPath: {xpath} (previously: {previous_xpath})", self.product_name)
                        setattr(self, xpath_tracker_attribute_name, xpath)
                    # else: no change, no log
                else:
                    log(f"Found {description} using XPath: {xpath}", self.product_name) # Log always if no tracker
                
                return element
            except NoSuchElementException:
                continue
        raise NoSuchElementException(f"Could not find {description} using any of the provided XPaths: {xpaths}")

    def run(self):
        options = selenium.webdriver.ChromeOptions() 
        options.add_argument("--headless=new") # Use the new headless mode
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1920,1080") # Set a default window size
        options.add_argument("--disable-gpu") # Often recommended for headless

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

        product_url = f"https://{self.amazon_host}/dp/{self.asin}"

        while not self.stop_event.is_set():
            sleep(5 + random.uniform(0, 3))
            if self.stop_event.is_set():
                break
            try:
                driver.get(f"{product_url}/?aod=0{f'&tag={self.amazon_tag}' if self.amazon_tag else ''}")
                sleep(10 + random.uniform(0, 3))
                if self.stop_event.is_set():
                    break

                # Check for CAPTCHA page
                try:
                    captcha_text_element = driver.find_element(by=By.XPATH, value="//h4[contains(text(), 'Fai clic sul pulsante qui sotto per continuare a fare acquisti')] | //h4[contains(text(), 'Type the characters you see in this image')] | //h4[contains(text(), 'Click the button below to continue shopping')] ")
                    if captcha_text_element:
                        log(f"CAPTCHA detected! Attempting to bypass by clicking 'Continue shopping' button.", self.product_name)
                        # Add random delay before clicking
                        random_delay = random.uniform(0, 3)
                        log(f"Waiting for {random_delay:.2f} seconds before clicking 'Continue shopping' button.", self.product_name)
                        sleep(random_delay)
                        # Find and click the "Continua con gli acquisti" button
                        continue_button = driver.find_element(by=By.XPATH, value="//button[contains(text(), 'Continua con gli acquisti')] | //button[contains(text(), 'Continue shopping')] | //button[contains(text(), 'Continue with your order')] ")
                        continue_button.click()
                        log(f"'Continue shopping' button clicked. Waiting for 3 seconds.", self.product_name)
                        sleep(3 + random.uniform(0, 3)) # Wait for the page to load after clicking the button
                except NoSuchElementException:
                    pass # No CAPTCHA detected, continue as usual

                # Check for product unavailability
                main_current_price = None # Default to an invalid price
                condition_text = "N/A" # Initialize with default value
                normalized_state = "unknown" # Initialize with default value
                try:
                    unavailable_element = driver.find_element(by=By.XPATH, value="//div[@id='availability']//span[contains(text(), 'Attualmente non disponibile')] | //div[@id='availability']//span[contains(text(), 'Currently unavailable')] | //div[@id='availability']//span[contains(text(), 'Non disponibile')] ")
                    if unavailable_element:
                        main_current_price = -1.0  # Product is unavailable
                except NoSuchElementException:
                    # Product is not explicitly marked as unavailable, proceed to check for main offer
                    pass

                # Check the main "Brand New" option (Featured Offer) only if not already determined as unavailable
                if main_current_price != -1.0:
                    try:
                        MAIN_OFFER_CONTAINER_XPATHS = [
                            "//div[@id='qualifiedBuybox']",
                            "//div[@id='newAccordionRow_0']",
                            "//div[contains(@class, 'aod-pinned-offer')]",
                            "//div[@id='aod-sticky-pinned-offer']",
                            "//div[contains(@class, 'aod-offer-group') and .//input[@name='submit.addToCart']]"
                        ]
                        main_offer_container = self._find_element_by_multiple_xpaths(driver, MAIN_OFFER_CONTAINER_XPATHS, "main offer container", "previous_main_offer_xpath")
                        price_whole_str = main_offer_container.find_element(by=By.XPATH, value=".//span[contains(@class, 'a-price-whole')]").text.replace('.', '').replace(',', '')
                        try:
                            price_fraction_str = main_offer_container.find_element(by=By.XPATH, value=".//span[contains(@class, 'a-price-fraction')]").text
                            main_current_price = float(f"{price_whole_str}.{price_fraction_str}")
                        except NoSuchElementException:
                            main_current_price = float(price_whole_str)

                        condition_text = "New" # Default to New
                        # Try to find any text within the main offer container that indicates "used"
                        try:
                            # Search for "Usato" (Used) or "Used" within the main offer container
                            used_element = main_offer_container.find_element(by=By.XPATH, value=".//*[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'usato')] | .//*[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'used')] ")
                            if used_element:
                                condition_text = used_element.text.strip() # Get the actual text if found
                        except NoSuchElementException:
                            pass # No explicit "used" text found, keep default "New"

                        normalized_state = "new"
                        condition_cleaned = condition_text.lower()
                        if "usato" in condition_cleaned or "used" in condition_cleaned:
                            normalized_state = "used"
                    except NoSuchElementException as e:
                        self._save_debug_html(driver, e, "main_offer")
                    except Exception as e:
                        exc_type, exc_value, exc_tb = sys.exc_info()
                        file_name = exc_tb.tb_frame.f_code.co_filename
                        line_number = exc_tb.tb_lineno
                        log(f"An unexpected error occurred while processing the main offer: {e} at file {file_name} line {line_number}")
                
                price_changed = main_current_price != self.previous_main_price

                if main_current_price == -1.0:
                    log_message = f"Main offer state: '{condition_text}' (normalized: '{normalized_state}'), price: UNAVAILABLE"
                elif main_current_price is None:
                    log_message = f"Main offer state: '{condition_text}' (normalized: '{normalized_state}'), price: ERROR_GETTING_PRICE"
                else:
                    log_message = f"Main offer state: '{condition_text}' (normalized: '{normalized_state}'), price: {main_current_price:.2f}"

                if main_current_price == -1.0:
                    if price_changed:
                        log(f"{log_message}", self.product_name)
                elif main_current_price is None:
                    if price_changed:
                        log(f"{log_message} - ERROR: unable to get main offer's current price...", self.product_name)
                elif self.object_state and normalized_state not in self.object_state:
                    if price_changed:
                        log(f"{log_message} - SKIPPING: State not in desired list {self.object_state}", self.product_name)
                elif main_current_price <= self.cut_price:
                    if price_changed:
                        log(f"{log_message} - ACCEPTED: Price is low enough.", self.product_name)
                    send_telegram_notification(f"{self.product_name} ({self.asin}) price is dropped to {main_current_price:.2f}! Link: {product_url}", self.product_name)
                    if not self.autocheckout:
                        main_add_to_cart_button = main_offer_container.find_element(by=By.XPATH, value=".//input[@id='add-to-cart-button']")
                        main_add_to_cart_button.click()
                        log(f"!!! Just added to cart !!!", self.product_name)
                    else:
                        #driver.find_element(by=By.XPATH, value='//*[@id="sc-buy-box-ptc-button"]/span/input').click()
                        sleep(0.5)
                        #driver.find_element(by=By.XPATH, value='//*[@id="a-autoid-0-announce"]').click()
                        #driver.find_element(by=By.XPATH, value='//*[@id="submitOrderButtonId"]/span/input').click()
                        log(f"!!! Just bought !!!", self.product_name)
                    
                else:
                    if price_changed:
                        log(f"{log_message} - SKIPPING: The current price is not low enough (i.e. > {self.cut_price:.2f})", self.product_name)
                
                # Update previous_main_price after all processing for the current iteration
                self.previous_main_price = main_current_price

                if self.stop_event.is_set(): # If main offer was processed and bought, exit
                    break

                offer_containers = driver.find_elements(by=By.XPATH, value="//div[contains(@class, 'aod-information-block') and @role='listitem' and .//input[@name='submit.addToCart']]")
                current_offer_count = len(offer_containers)
                if current_offer_count != len(self.previous_offer_prices):
                    log(f"{current_offer_count} other offers found", self.product_name)

                if not offer_containers:
                    driver.refresh()
                    sleep(2 + random.uniform(0, 3))
                    continue

                new_offer_prices = []
                for i, offer in enumerate(offer_containers):
                    try:
                        price_changed = False # Default to false
                        
                        condition_text = "N/A"
                        try:
                            condition_span = offer.find_element(by=By.XPATH, value=".//div[@id='aod-offer-heading']/span")
                            condition_text = condition_span.text.strip()
                        except NoSuchElementException:
                            log(f"Could not find condition for an offer, skipping.", self.product_name)
                            continue

                        normalized_state = "unknown"
                        condition_cleaned = " ".join(condition_text.split()).lower()
                        
                        condition_mappings = {
                            "new": ["nuovo", "new"],
                            "used-likenew": ["usato - come nuovo", "used - like new"],
                            "used-very good": ["usato - ottime condizioni", "used - very good"],
                            "used-good": ["usato - buone condizioni", "used - good"],
                            "used-acceptable": ["usato - condizioni accettabili", "used - acceptable"],
                            "used": ["usato", "used"]
                        }

                        for state, keywords in condition_mappings.items():
                            for keyword in keywords:
                                if keyword in condition_cleaned:
                                    normalized_state = state
                                    break
                            if normalized_state != "unknown":
                                break

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

                        if current_price < 0:
                            if price_changed:
                                log(f"{log_message} - ERROR: unable to get {i}th offer's current price...")
                            continue
                            
                        if self.object_state and normalized_state not in self.object_state:
                            if price_changed:
                                log(f"{log_message} - SKIPPING: State not in desired list {self.object_state}")
                            continue

                        if current_price <= self.cut_price:
                            if price_changed:
                                log(f"{log_message} - ACCEPTED: Price is low enough.")
                            send_telegram_notification(f"{self.product_name} ({self.asin}) price is dropped to {current_price:.2f}! Link: {product_url}", self.product_name)
                            
                            if not self.autocheckout:
                                add_to_cart_button = offer.find_element(by=By.XPATH, value=".//input[@name='submit.addToCart']")
                                add_to_cart_button.click()
                                log(f"!!! Just added to cart !!!", self.product_name)
                            else:
                                sleep(0.5)
                                #driver.find_element(by=By.XPATH, value='//*[@id="sc-buy-box-ptc-button"]/span/input').click()
                                log(f"!!! Just bought !!!", self.product_name)
                            
                            check = False
                            break
                        else:
                            if price_changed:
                                log(f"{log_message} - SKIPPING: The current price is not low enough (i.e. > {self.cut_price:.2f})")
                    except Exception as e:
                        self._save_debug_html(driver, e, "other_offer")

                self.previous_offer_prices = new_offer_prices
                
                if self.stop_event.is_set(): # If one of the other offers was processed and bought, exit
                    break

            except Exception as e:
                exc_type, exc_value, exc_tb = sys.exc_info()
                file_name = exc_tb.tb_frame.f_code.co_filename
                line_number = exc_tb.tb_lineno
                log(f"Error finding offers: {e} at file {file_name} line {line_number}")
                driver.refresh()
                sleep(2 + random.uniform(0, 3))
            

        driver.quit()
    
        


amazon_host=os.getenv("AMAZON_HOST") or "www.amazon.it"
amazon_tag=os.getenv("AMAZON_TAG") or None

amazon_email=os.getenv("AMAZON_EMAIL")
amazon_psw=os.getenv("AMAZON_PASSWORD")

# Load products from TOML file
products_file = 'products.toml'
sample_file = 'products.sample.toml'

try:
    with open(products_file, 'r', encoding='utf-8') as f:
        products_toml = toml.load(f)
except FileNotFoundError:
    log(f"'{products_file}' not found.")
    try:
        with open(sample_file, 'r', encoding='utf-8') as s, open(products_file, 'w', encoding='utf-8') as p:
            p.write(s.read())
        log(f"Created '{products_file}' from '{sample_file}'. Please customize it with your products and run the script again.")
    except FileNotFoundError:
        log(f"'{sample_file}' not found! Cannot create {products_file}... Bail out!")
    sys.exit()

products = []
for name, details in products_toml.items():
    details['name'] = name
    products.append(details)

active_threads = {}

def start_monitoring_product(product_data):
    asin = product_data['asin']
    if asin in active_threads:
        log(f"Product {asin} is already being monitored.")
        return

    stop_event = threading.Event()
    t = pricesdrop_bot(
        amazon_host=amazon_host, 
        amazon_tag=amazon_tag, 
        amazon_email=amazon_email, 
        amazon_psw=amazon_psw, 
        product=product_data,
        stop_event=stop_event
    )
    t.start()
    active_threads[asin] = {'thread': t, 'stop_event': stop_event}
    log(f"Started monitoring product '{product_data['name']}' ({asin}).")

def stop_monitoring_product(asin):
    if asin not in active_threads:
        log(f"Product {asin} is not being monitored.")
        return

    log(f"Stopping monitoring for product {asin}...")
    active_threads[asin]['stop_event'].set()
    active_threads[asin]['thread'].join()
    del active_threads[asin]
    log(f"Stopped monitoring for product {asin}.")

def amazon_monitor_main():
    # Load products from TOML file
    products_file = 'products.toml'
    sample_file = 'products.sample.toml'

    try:
        with open(products_file, 'r', encoding='utf-8') as f:
            products_toml = toml.load(f)
    except FileNotFoundError:
        log(f"'{products_file}' not found.")
        try:
            with open(sample_file, 'r', encoding='utf-8') as s, open(products_file, 'w', encoding='utf-8') as p:
                p.write(s.read())
            log(f"Created '{products_file}' from '{sample_file}'. Please customize it with your products and run the script again.")
        except FileNotFoundError:
            log(f"'{sample_file}' not found! Cannot create {products_file}... Bail out!")
        sys.exit()

    products = []
    for name, details in products_toml.items():
        details['name'] = name
        products.append(details)

    for item in products:
        log(f"Start looking for price drop on product '{item['name']}': {('buy it' if item.get('autocheckout') else 'add it to cart')} if price drops under {item['cut_price']:.2f}...")
        start_monitoring_product(item)


if __name__ == '__main__':
    # Start Amazon monitoring in a separate thread
    amazon_thread = threading.Thread(target=amazon_monitor_main)
    amazon_thread.start()

    # Run Telegram bot in the main thread
    telegram_bot_main()
