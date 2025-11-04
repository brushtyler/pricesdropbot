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

async def post_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /post <ASIN> <message>")
        return

    asin = context.args[0]
    custom_message = " ".join(context.args[1:])

    driver = None
    try:
        # Start a new driver session
        options = selenium.webdriver.ChromeOptions()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-gpu")
        driver = selenium.webdriver.Chrome(options=options)

        # Load cookies to be logged in
        if not os.path.exists(".cookies.pkl"):
            await update.message.reply_text("Cookies file not found. Cannot proceed without being logged in.")
            return
            
        driver.get(f"https://{amazon_host}/")
        with open(".cookies.pkl", "rb") as f:
            cookies = pickle.load(f)
            for cookie in cookies:
                if 'domain' in cookie:
                    del cookie['domain']
                driver.add_cookie(cookie)
        driver.refresh()

        # Navigate to product page
        product_url = f"https://{amazon_host}/dp/{asin}/?offerta_selezionata_da={bot_name}&aod=0{f'&tag={amazon_tag}' if amazon_tag else ''}"
        scraped_data = scrape_product_data(driver, product_url, asin, asin, amazon_tag)

        product_name = scraped_data["product_name"]
        if not product_name:
            await update.message.reply_text(f"Could not retrieve product name for {asin}.")
            return

        price = scraped_data["main_current_price"]
        if price <= 0:
            await update.message.reply_text(f"Could not retrieve a valid price for {asin}.")
            return

        item_count = scraped_data["item_count"]

        # Generate Shortlink
        shortlink = generate_shortlink(driver, asin, product_name)
        if not shortlink:
            await update.message.reply_text(f"Failed to generate shortlink for {asin}. The notification will be sent without it.")

        # Construct and send message
        item_count_str = ""
        if item_count != 1:
            item_count_str = f", {item_count} pezzi"
        final_message = f"{product_name}{item_count_str} a {price:.2f}EUR\n{custom_message}\n{shortlink}"
        send_telegram_notification(final_message, product_name)
        await update.message.reply_text("Post notification sent.")

    finally:
        if driver:
            driver.quit()

async def reload_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Reloading products from products.toml...")
    
    new_products_list = load_products_from_toml()
    if new_products_list is None:
        await update.message.reply_text("Could not load products.toml. Please check the logs.")
        return

    new_products_map = {p['asin']: p for p in new_products_list}
    new_asins = set(new_products_map.keys())
    current_asins = set(active_threads.keys())

    asins_to_remove = current_asins - new_asins
    asins_to_add = new_asins - current_asins
    asins_to_check = current_asins.intersection(new_asins)

    removed_count = 0
    for asin in asins_to_remove:
        stop_monitoring_product(asin)
        removed_count += 1
    if removed_count > 0:
        log(f"Stopped monitoring {removed_count} product(s) removed from the file.")
        await update.message.reply_text(f"Stopped monitoring {removed_count} product(s) removed from the file.")

    added_count = 0
    for asin in asins_to_add:
        start_monitoring_product(new_products_map[asin])
        added_count += 1
    if added_count > 0:
        log(f"Started monitoring {added_count} new product(s).")
        await update.message.reply_text(f"Started monitoring {added_count} new product(s).")

    updated_count = 0
    for asin in asins_to_check:
        old_product_data = active_threads[asin].get('product_data')
        new_product_data = new_products_map[asin]

        if old_product_data != new_product_data:
            log(f"Product {asin} data has changed. Reloading.")
            stop_monitoring_product(asin)
            start_monitoring_product(new_product_data)
            updated_count += 1

    if updated_count > 0:
        log(f"Reloaded {updated_count} product(s) with updated configuration.")
        await update.message.reply_text(f"Reloaded {updated_count} product(s) with updated configuration.")

    await update.message.reply_text("Reload complete.")


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
    application = Application.builder().token(bot_token).build()

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
    application.add_handler(CommandHandler("post", post_command))
    application.add_handler(CommandHandler("reload", reload_command))

    log("Telegram bot started polling...")
    application.run_polling()

def send_telegram_notification(message, product_name=None, image_url=None):
    if bot_token and chat_id:
        if image_url:
            url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
            payload = {
                "chat_id": chat_id,
                "photo": image_url,
                "caption": message,
                "parse_mode": "HTML"
            }
        else:
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


def scrape_product_data(driver, product_url, product_name_for_log, asin, amazon_tag):
    driver.get(product_url)
    sleep(10 + random.uniform(0, 3))
    handle_captcha(driver, product_name_for_log)

    scraped_data = {
        "product_name": "",
        "item_count": 1,
        "product_image_url": None,
        "main_current_price": -1.0,
        "condition_text": "N/A",
        "normalized_state": "unknown",
        "is_unavailable": False,
        "main_offer_container": None,
    }

    # Get product name
    try:
        scraped_data["product_name"] = driver.find_element(by=By.ID, value="productTitle").text.strip()
    except Exception as e:
        log(f"Could not find product name: {e}", product_name_for_log)

    # Retrieve item count
    try:
        item_count_xpaths = [
            "//tr[contains(@class, 'po-number_of_items')]/td[2]/span",
            "//div[contains(@data-feature-name, 'metaData') and .//span[contains(text(), 'Numero di articoli')]]//span[@class='a-size-base a-color-tertiary']",
            "//div[contains(@data-feature-name, 'metaData') and .//span[contains(text(), 'Number of Items')]]//span[@class='a-size-base a-color-tertiary']",
            "//div[@id='detailBullets_feature_div']//span[contains(text(), 'Numero di articoli')]/following-sibling::span",
            "//div[@id='detailBullets_feature_div']//span[contains(text(), 'Number of Items')]/following-sibling::span"
        ]
        for xpath in item_count_xpaths:
            try:
                item_count_element = driver.find_element(by=By.XPATH, value=xpath)
                scraped_data["item_count"] = int(item_count_element.text)
                break  # if found, break the loop
            except (NoSuchElementException, ValueError):
                continue  # if not found, try the next xpath
    except Exception as e:
        log(f"Could not find or parse item count: {e}", product_name_for_log)
    
    # Try to find the product image URL
    try:
        image_xpaths = [
            "//img[@id='landingImage']",
            "//img[@id='imgBlkFront']",
            "//div[contains(@class, 'imgTagWrapper')]/img"
        ]
        for xpath in image_xpaths:
            try:
                image_element = driver.find_element(by=By.XPATH, value=xpath)
                scraped_data["product_image_url"] = image_element.get_attribute('src')
                if scraped_data["product_image_url"]:
                    break
            except NoSuchElementException:
                continue
    except Exception as e:
        log(f"Could not find product image: {e}", product_name_for_log)

    # Check for product unavailability
    try:
        unavailable_element = driver.find_element(by=By.XPATH, value="//div[@id='availability']//span[contains(text(), 'Attualmente non disponibile')] | //div[@id='availability']//span[contains(text(), 'Currently unavailable')] | //div[@id='availability']//span[contains(text(), 'Non disponibile')] ")
        if unavailable_element:
            scraped_data["is_unavailable"] = True
            scraped_data["main_current_price"] = -1.0
    except NoSuchElementException:
        pass

    # Check the main "Brand New" option (Featured Offer) only if not already determined as unavailable
    if not scraped_data["is_unavailable"]:
        try:
            MAIN_OFFER_CONTAINER_XPATHS = [
                "//div[@id='qualifiedBuybox']",
                "//div[@id='newAccordionRow_0']",
                "//div[@id='newAccordionRow_1']",
                "//div[@data-a-accordion-row-name='newAccordionRow']",
                "//div[contains(@class, 'aod-pinned-offer')]",
                "//div[@id='aod-sticky-pinned-offer']",
                "//div[contains(@class, 'aod-offer-group') and .//input[@name='submit.addToCart']]",
                "//div[@id='desktop_qualifiedBuyBox']"
            ]
            main_offer_container, _ = find_element_by_multiple_xpaths(driver, MAIN_OFFER_CONTAINER_XPATHS, "main offer container")
            scraped_data["main_offer_container"] = main_offer_container

            price_whole_str = main_offer_container.find_element(by=By.XPATH, value=".//span[contains(@class, 'a-price-whole')]").text.replace('.', '').replace(',', '')
            try:
                price_fraction_str = main_offer_container.find_element(by=By.XPATH, value=".//span[contains(@class, 'a-price-fraction')]").text
                scraped_data["main_current_price"] = float(f"{price_whole_str}.{price_fraction_str}")
            except NoSuchElementException:
                scraped_data["main_current_price"] = float(price_whole_str)

            scraped_data["condition_text"] = "New"
            try:
                used_element = main_offer_container.find_element(by=By.XPATH, value=".//*[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'usato')] | .//*[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'used')] ")
                if used_element:
                    scraped_data["condition_text"] = used_element.text.strip()
            except NoSuchElementException:
                pass

            scraped_data["normalized_state"] = "new"
            condition_cleaned = scraped_data["condition_text"].lower()
            if "usato" in condition_cleaned or "used" in condition_cleaned:
                scraped_data["normalized_state"] = "used"
        except NoSuchElementException as e:
            save_debug_html(driver, e, "main_offer", product_name_for_log, asin)
        except Exception as e:
            save_debug_html(driver, e, "main_offer", product_name_for_log, asin)
            exc_type, exc_value, exc_tb = sys.exc_info()
            file_name = exc_tb.tb_frame.f_code.co_filename
            line_number = exc_tb.tb_lineno
            log(f"An unexpected error occurred while processing the main offer: {e} at file {file_name} line {line_number}", product_name_for_log)

    return scraped_data

def find_element_by_multiple_xpaths(driver, xpaths, description="element"):
    for xpath in xpaths:
        try:
            element = driver.find_element(by=By.XPATH, value=xpath)
            return element, xpath
        except NoSuchElementException:
            continue
    raise NoSuchElementException(f"Could not find {description} using any of the provided XPaths: {xpaths}")

def save_debug_html(driver, exception, context_name, product_name, asin):
    exc_type, exc_value, exc_tb = sys.exc_info()
    file_name = exc_tb.tb_frame.f_code.co_filename
    line_number = exc_tb.tb_lineno
    current_url = driver.current_url
    error_message = f"URL: {current_url}, File: {file_name}, Line: {line_number}, Error: {exception}"
    
    logs_dir = "logs"
    if not os.path.exists(logs_dir):
        os.makedirs(logs_dir)
        
    safe_product_name = product_name.replace(' ', '_')
    html_file_name = os.path.join(logs_dir, f"debug_{context_name}_not_found_{safe_product_name}_{asin}.html")
    
    with open(html_file_name, "w", encoding="utf-8") as f:
        f.write(f"<!-- {error_message} -->\n")
        f.write(driver.page_source)
        
    log(f"Error during '{context_name}' processing. Page HTML saved to {html_file_name} for debugging. {error_message}", product_name)

def handle_captcha(driver, product_name_for_log):
    try:
        captcha_text_element = driver.find_element(by=By.XPATH, value="//h4[contains(text(), 'Fai clic sul pulsante qui sotto per continuare a fare acquisti')] | //h4[contains(text(), 'Type the characters you see in this image')] | //h4[contains(text(), 'Click the button below to continue shopping')] ")
        if captcha_text_element:
            log(f"CAPTCHA detected! Attempting to bypass by clicking 'Continue shopping' button.", product_name_for_log)
            random_delay = random.uniform(0, 3)
            log(f"Waiting for {random_delay:.2f} seconds before clicking 'Continue shopping' button.", product_name_for_log)
            sleep(random_delay)
            continue_button = driver.find_element(by=By.XPATH, value="//button[contains(text(), 'Continua con gli acquisti')] | //button[contains(text(), 'Continue shopping')] | //button[contains(text(), 'Continue with your order')] ")
            continue_button.click()
            log(f"'Continue shopping' button clicked. Waiting for 3 seconds.", product_name_for_log)
            sleep(3 + random.uniform(0, 3))
            return True # CAPTCHA was handled
    except NoSuchElementException:
        pass # No CAPTCHA
    return False # No CAPTCHA was found/handled

def generate_shortlink(driver, asin, product_name):
    shortlink = ""
    try:
        get_link_button = driver.find_element(by=By.ID, value="amzn-ss-get-link-button")
        get_link_button.click()
        log(f"Clicked 'amzn-ss-get-link-button' for {asin}", product_name)
        sleep(2)
        shortlink_textarea = driver.find_element(by=By.ID, value="amzn-ss-text-shortlink-textarea")
        shortlink = shortlink_textarea.text
        log(f"Generated shortlink for {asin}: {shortlink}", product_name)
    except Exception as e:
        log(f"Failed to generate shortlink for {asin}: {e}", product_name)
    return shortlink

class pricesdrop_bot(threading.Thread):
    def __init__(self, amazon_host, amazon_tag, product, stop_event):
        self.amazon_host=amazon_host
        self.amazon_tag=amazon_tag
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
        self.product_url = f"https://{self.amazon_host}/dp/{self.asin}/?offerta_selezionata_da={bot_name}&aod=0{f'&tag={self.amazon_tag}' if self.amazon_tag else ''}"
        threading.Thread.__init__(self) 

    def run(self):
        options = selenium.webdriver.ChromeOptions()
        options.add_argument("--headless=new") # Always headless for monitoring
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-gpu")

        driver = selenium.webdriver.Chrome(options=options) 

        # Always load cookies, as login is handled externally
        driver.get(f"https://{self.amazon_host}/")
        with open(".cookies.pkl", "rb") as f:
            cookies = pickle.load(f)
            for cookie in cookies:
                if 'domain' in cookie:
                    del cookie['domain']
                driver.add_cookie(cookie)
        driver.refresh()

        while True:
            sleep(5 + random.uniform(0, 3))
            if self.stop_event.is_set():
                break
            try:
                scraped_data = scrape_product_data(driver, self.product_url, self.product_name, self.asin, self.amazon_tag)
                if self.stop_event.is_set():
                    break

                self.product_image_url = scraped_data["product_image_url"]
                main_current_price = scraped_data["main_current_price"]
                condition_text = scraped_data["condition_text"]
                normalized_state = scraped_data["normalized_state"]
                main_offer_container = scraped_data["main_offer_container"] # Keep for add to cart button

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
                    shortlink = generate_shortlink(driver, self.asin, self.product_name)
                    if not shortlink:
                        shortlink = self.product_url # Fallback to full URL if shortlink generation fails
                    send_telegram_notification(f"{self.product_name} ({self.asin}) price is dropped to {main_current_price:.2f}! Link: {shortlink}", self.product_name, image_url=self.product_image_url)
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
                            shortlink = generate_shortlink(driver, self.asin, self.product_name)
                            if not shortlink:
                                shortlink = self.product_url # Fallback to full URL if shortlink generation fails
                            send_telegram_notification(f"{self.product_name} ({self.asin}) price is dropped to {current_price:.2f}! Link: {shortlink}", self.product_name, image_url=self.product_image_url)
                            
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
                        save_debug_html(driver, e, "other_offer", self.product_name, self.asin)

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

def load_products_from_toml():
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
        return None

    products = []
    for name, details in products_toml.items():
        details['name'] = name
        products.append(details)
    return products

def start_monitoring_product(product_data):
    asin = product_data['asin']
    if asin in active_threads:
        log(f"Product {asin} is already being monitored.")
        return

    stop_event = threading.Event()
    t = pricesdrop_bot(
        amazon_host=amazon_host, 
        amazon_tag=amazon_tag, 
        product=product_data,
        stop_event=stop_event
    )
    t.start()
    active_threads[asin] = {'thread': t, 'stop_event': stop_event, 'product_data': product_data}
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

def amazon_monitor_main(monitoring_started_event):
    if os.path.exists(".cookies.pkl"):
        log("Cookies file found. Checking session validity...")
        check_options = selenium.webdriver.ChromeOptions()
        check_options.add_argument("--no-sandbox")
        check_options.add_argument("--disable-dev-shm-usage")
        check_options.add_argument("--window-size=1920,1080")
        check_options.add_argument("--disable-gpu")
        check_options.add_argument("--headless=new")
        check_driver = selenium.webdriver.Chrome(options=check_options)
        check_driver.get(f"https://{amazon_host}/")
        with open(".cookies.pkl", "rb") as f:
            cookies = pickle.load(f)
            for cookie in cookies:
                if 'domain' in cookie:
                    del cookie['domain']
                check_driver.add_cookie(cookie)
        
        check_driver.get(f"https://{amazon_host}/gp/css/homepage.html")
        sleep(2) # Give time for redirection
        
        if "signin" in check_driver.current_url:
            log("Session from cookies is invalid. Deleting cookies and performing new login.")
            os.remove(".cookies.pkl")
        else:
            log("Session is valid.")
        check_driver.quit()

    if not os.path.exists(".cookies.pkl"):
        log("No cookies found. Performing login in non-headless mode...")
        login_options = selenium.webdriver.ChromeOptions()
        login_options.add_argument("--no-sandbox")
        login_options.add_argument("--disable-dev-shm-usage")
        login_options.add_argument("--window-size=1920,1080")
        login_options.add_argument("--disable-gpu")
        login_driver = selenium.webdriver.Chrome(options=login_options)

        login_driver.get(f"https://{amazon_host}/ap/signin?openid.pape.max_auth_age=0&openid.return_to=https%3A%2F%2F{amazon_host}%2Fgp%2Fcart%2Fview.html%2Fref%3Dnav_ya_signin%3F&openid.identity=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0%2Fidentifier_select&openid.assoc_handle=itflex&openid.mode=checkid_setup&openid.claimed_id=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2F0%2Fidentifier_select&openid.ns=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0")
        sleep(1)
        login_driver.find_element(by=By.XPATH, value='//*[@id="ap_email"]').send_keys(amazon_email)
        sleep(1)
        login_driver.find_element(by=By.XPATH, value='//*[@id="continue"]').click()
        sleep(1)
        login_driver.find_element(by=By.XPATH, value='//*[@id="ap_password"]').send_keys(amazon_psw)
        sleep(1)
        login_driver.find_element(by=By.XPATH, value='//*[@id="signInSubmit"]').click()

        input("Please complete the login on the browser. If you have to complete a 2FA, do it. Once you are logged in, press Enter here to continue...") # Wait for user to complete login and 2FA (if any)

        # Save cookies to avoid always performing login+2FA
        with open(".cookies.pkl", "wb") as f:
            pickle.dump(login_driver.get_cookies(), f)
        login_driver.quit() # Quit the non-headless driver after login
        log("Login completed and cookies saved.")

    # Load products from TOML file
    log("Loading product list...")
    products = load_products_from_toml()
    if products is None:
        sys.exit()

    for item in products:
        log(f"Start looking for price drop on product '{item['name']}': {('buy it' if item.get('autocheckout') else 'add it to cart')} if price drops under {item['cut_price']:.2f}...")
        start_monitoring_product(item)

    # Signal that monitoring has started
    monitoring_started_event.set()
    log("Amazon monitoring initial setup complete. Telegram bot can now start.")


bot_name = os.getenv("TELEGRAM_BOT_NAME") or "pricesdrop.it"
bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
chat_id = os.getenv("TELEGRAM_CHAT_ID")

amazon_host=os.getenv("AMAZON_HOST") or "www.amazon.it"
amazon_tag=os.getenv("AMAZON_TAG") or None
amazon_email=os.getenv("AMAZON_EMAIL")
amazon_psw=os.getenv("AMAZON_PASSWORD")


# Load products from TOML file
products = load_products_from_toml()
if products is None:
    sys.exit()

active_threads = {}

if __name__ == '__main__':
    monitoring_started_event = threading.Event()

    # Start Amazon monitoring in a separate thread
    amazon_thread = threading.Thread(target=amazon_monitor_main, args=(monitoring_started_event,))
    amazon_thread.start()

    # Wait for Amazon monitoring to complete its initial setup
    monitoring_started_event.wait()
    log("Telegram bot starting...")

    # Run Telegram bot in the main thread
    telegram_bot_main()
