#!/usr/bin/env python3

import platform
import subprocess
import re
import json

import selenium
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from time import sleep
import threading
import os
import pickle
from selenium.common.exceptions import NoSuchDriverException, NoSuchElementException, TimeoutException
from datetime import datetime
import sys
import toml
import random
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from dotenv import load_dotenv

load_dotenv()

user_agent_string = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"

def create_chrome_driver(headless=True):
    options = selenium.webdriver.ChromeOptions()
    options.add_argument(f"user-agent={user_agent_string}")
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox");
    options.add_argument("--disable-dev-shm-usage");
    options.add_argument("--disable-renderer-backgrounding");
    options.add_argument("--disable-background-timer-throttling");
    options.add_argument("--disable-backgrounding-occluded-windows");
    options.add_argument("--disable-client-side-phishing-detection");
    options.add_argument("--disable-crash-reporter");
    options.add_argument("--disable-oopr-debug-crash-dump");
    options.add_argument("--no-crash-upload");
    options.add_argument("--disable-gpu");
    options.add_argument("--disable-extensions");
    options.add_argument("--disable-low-res-tiling");
    options.add_argument("--log-level=3");
    options.add_argument("--silent");
    options.add_argument("--window-size=1920,1080")
    try:
        return selenium.webdriver.Chrome(options=options)
    except NoSuchDriverException:
        pass
    service = selenium.webdriver.chrome.service.Service(executable_path='/usr/bin/chromedriver')
    return selenium.webdriver.Chrome(service=service, options=options)

def log(message, product_name=None):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}]{f' [{product_name}]' if product_name else ''} {message}")

# States for adding a product
ASK_NAME, ASK_CUT_PRICE = range(2)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    await update.message.reply_text("Hello! I am your Prices Drop Bot. Use /add to add a product or /delete to remove one.")

async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not context.args:
        await update.message.reply_text("Please provide the ASIN of the product to add. Usage: /add <ASIN>")
        return
    asin_to_add = context.args[0]
    context.user_data['asin'] = asin_to_add
    await update.message.reply_text("Please send me the name of the product.")
    return ASK_NAME

async def add_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    context.user_data['name'] = update.message.text
    await update.message.reply_text("Please send me the cut price (e.g., 100.50).")
    return ASK_CUT_PRICE

async def add_cut_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    try:
        context.user_data['cut_price'] = float(update.message.text)
    except ValueError:
        await update.message.reply_text("Invalid price. Please enter a number (e.g., 100.50).")
        return ASK_CUT_PRICE

    product_data = {
        "name": context.user_data['name'],
        "asin": context.user_data['asin'],
        "cut_price": context.user_data['cut_price'],
        "autoaddtocart": False,
        "autocheckout": False
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
        "autoaddtocart": product_data['autoaddtocart'],
        "autocheckout": product_data['autocheckout']
    }

    with open(products_file, 'w', encoding='utf-8') as f:
        toml.dump(products_toml, f)

    # Start monitoring the new product
    start_monitoring_product(product_data)

    await update.message.reply_text(f"Product '{product_data['name']}' added and monitoring started!")
    return ConversationHandler.END

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    await update.message.reply_text("Operation cancelled.")
    return ConversationHandler.END

async def delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
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
    if not update.message:
        return
    if len(context.args) < 3:
        await update.message.reply_text("Usage: /post <ASIN> <seller_id> <message>")
        return

    asin = context.args[0]
    seller_id = context.args[1]
    custom_message = " ".join(context.args[2:])
    log_id = f"/post {asin}"

    driver = None
    try:
        # Start a new driver session
        driver = create_chrome_driver(headless=True)

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
        product_url = get_product_url(asin, seller_id)
        scraped_data = scrape_product_data(driver, product_url, log_id, asin, use_rufus_ai=True)

        product_name = scraped_data["product_name"]
        if not product_name:
            await update.message.reply_text(f"Could not retrieve product name for {asin}.")
            return

        product_image_url = scraped_data["product_image_url"]
        price = scraped_data["current_price"]
        if price <= 0:
            await update.message.reply_text(f"Could not retrieve a valid price for {asin}.")
            return

        items_count = scraped_data["items_count"]

        # Generate Shortlink
        shortlink = generate_shortlink(driver, asin, log_id)
        if not shortlink:
            shortlink = get_affiliate_link(asin, amazon_tag, seller_id) # Fallback to full URL if shortlink generation fails

        # Construct and send message
        items_count_str = ""
        if items_count != 1:
            items_count_str = f", {items_count} pezzi"
        final_message = f"{product_name}{items_count_str} a {price:.2f}EUR\n{custom_message}\n{shortlink}"

        send_telegram_notification(final_message, image_url=product_image_url, log_id=log_id)
        await update.message.reply_text("Post notification sent.")

    finally:
        if driver:
            driver.quit()

async def get_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /get <ASIN> <seller_id> [options]")
        return

    asin = context.args[0]
    seller_id = context.args[1]
    options = context.args[2].split(',') if len(context.args) >= 3 else []
    debug = "debug" in options
    log_id = f"/get {asin}"

    driver = None
    try:
        # Start a new driver session
        driver = create_chrome_driver(headless=not debug)

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
        product_url = get_product_url(asin, seller_id)
        scraped_data = scrape_product_data(driver, product_url, log_id, asin, use_rufus_ai=True)

        product_name = scraped_data["product_name"]
        if not product_name:
            await update.message.reply_text(f"Could not retrieve product name for {asin}.")
            return

        product_image_url = scraped_data["product_image_url"]
        price = scraped_data["current_price"]
        items_count = scraped_data["items_count"]
        sold_by = scraped_data["sold_by"]
        ships_from = scraped_data["ships_from"]
        affiliate_link = get_affiliate_link(asin, amazon_tag, seller_id)
        product_brand_ai = scraped_data["product_brand_ai"]
        product_name_ai = scraped_data["product_name_ai"]
        product_description_ai = scraped_data["product_description_ai"]
        product_items_count_ai = scraped_data["product_items_count_ai"]
        product_sold_by_ai = scraped_data["product_sold_by_ai"]
        product_ships_from_ai = scraped_data["product_ships_from_ai"]
        product_by_amazon_ai = scraped_data["product_by_amazon_ai"]
        product_prime_ai = scraped_data["product_prime_ai"]

        # Construct and send message
        message = f"""
Product Information for ASIN: {asin}

Rufus AI>
        Brand: {product_brand_ai}
        Name: {product_name_ai}
        Description: {product_description_ai}
        Items Count: {product_items_count_ai}
        Sold By: {product_sold_by_ai}
        Ships From: {product_ships_from_ai}
        By Amazon: {product_by_amazon_ai}
        Prime: {product_prime_ai}

DOM>
        Full Title: {product_name}
        Items Count: {items_count}
        Price: {price:.2f} EUR
        Sold By: {sold_by}
        Ships From: {ships_from}
        Image URL: {product_image_url}
        Full Link: {product_url}
        Affiliate Link: {affiliate_link}
        """

        await update.message.reply_text(message)

        if debug:
            sleep(60)

    finally:
        if driver:
            driver.quit()

async def offers_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /offers <ASIN>")
        return

    asin = context.args[0]
    options = context.args[1].split(',') if len(context.args) >= 2 else []
    debug = "debug" in options
    log_id = f"/offers {asin}"

    driver = None
    try:
        # Start a new driver session
        driver = create_chrome_driver(headless=not debug)

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

        # First, navigate to the standard product page
        product_url = get_product_url(asin)
        driver.get(product_url)
        WebDriverWait(driver, 30).until(
            lambda d: d.execute_script("return document.readyState == 'complete'")
        )
        
        # Add a small delay to mimic human behavior
        sleep(2 + random.uniform(0, 3))

        # Now, get all offers from the AOD page
        offers = get_all_offers(driver, asin, log_id)

        if not offers:
            await update.message.reply_text(f"No offers found for ASIN {asin}.")
            return

        # Format the message
        message = f"Offers for ASIN: {asin}\n\n"
        for offer in offers:
            price = offer.get('price')
            if isinstance(price, float):
                message += f"- Price: {price:.2f} EUR\n"
            else:
                message += f"- Price: {price or 'N/A'}\n"
            
            message += f"  Condition: {offer.get('condition', 'N/A')}\n"
            message += f"  Sold by: {offer.get('sold_by', 'N/A')}\n"
            message += f"  Ships from: {offer.get('ships_from', 'N/A')}\n"
            if offer.get('is_pinned'):
                message += "  (Pinned Offer)\n"
            message += "\n"

        await update.message.reply_text(message)

    finally:
        if driver:
            driver.quit()


async def reload_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
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
    if not update.message:
        return
    if not active_threads:
        await update.message.reply_text("No products are currently being monitored.")
        return

    message = "Currently monitored products:\n"
    for asin, thread_info in active_threads.items():
        product_name = thread_info['thread'].product_name
        cut_price = thread_info['thread'].cut_price
        autocheckout = thread_info['thread'].autocheckout
        autoaddtocart = thread_info['thread'].autoaddtocart
        interval = thread_info['thread'].interval
        seller_id = thread_info['thread'].seller_id
        message += f"- <b>{product_name}</b> (ASIN: {asin}, Cut Price: {cut_price:.2f}, Autoaddtocart: {autoaddtocart}, Autocheckout: {autocheckout}, Interval: {interval}s, Seller ID: {seller_id})\n"
    await update.message.reply_text(message, parse_mode="HTML")

async def info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not context.args:
        await update.message.reply_text("Please provide the ASIN of the product. Usage: /info <ASIN>")
        return

    asin = context.args[0]
    if asin not in active_threads:
        await update.message.reply_text(f"Product with ASIN {asin} is not currently being monitored.")
        return

    thread_info = active_threads[asin]
    monitor_thread = thread_info['thread']

    last_price = monitor_thread.last_price
    last_check_time = monitor_thread.last_check_time
    price_history = monitor_thread.price_history
    seller_id = monitor_thread.seller_id

    if not price_history:
        message = f"No price history available for ASIN {asin}."
    else:
        # price_history is a list of tuples, so we need to extract the prices for calculations
        prices = [item[0] for item in price_history]
        avg_price = sum(prices) / len(prices)

        # Find min and max with their timestamps
        min_price_tuple = min(price_history, key=lambda item: item[0])
        max_price_tuple = max(price_history, key=lambda item: item[0])

        message = f"<b>Monitoring data for {monitor_thread.product_name} (ASIN: {asin}):</b>\n"
        message += f"Seller ID: {seller_id}\n"
        message += f"Last Price: {last_price:.2f} EUR on {last_check_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        message += f"Max Price: {max_price_tuple[0]:.2f} EUR on {max_price_tuple[1].strftime('%Y-%m-%d %H:%M:%S')}\n"
        message += f"Min Price: {min_price_tuple[0]:.2f} EUR on {min_price_tuple[1].strftime('%Y-%m-%d %H:%M:%S')}\n"
        message += f"Average Price: {avg_price:.2f} EUR\n"

    await update.message.reply_text(message, parse_mode="HTML")


def telegram_bot_main():
    application = Application.builder().token(bot_token).build()

    # Handlers
    application.add_handler(CommandHandler("start", start_command))

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("add", add_command)],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_name)],
            ASK_CUT_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_cut_price)],
        },
        fallbacks=[CommandHandler("cancel", cancel_command)],
    )
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("delete", delete_command))
    application.add_handler(CommandHandler("list", list_command))
    application.add_handler(CommandHandler("post", post_command))
    application.add_handler(CommandHandler("get", get_command))
    application.add_handler(CommandHandler("offers", offers_command))
    application.add_handler(CommandHandler("reload", reload_command))
    application.add_handler(CommandHandler("info", info_command))

    log("Telegram bot started polling...")
    application.run_polling()

def send_telegram_notification(message, image_url=None, log_id=None):
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
                log("Telegram notification sent successfully.", log_id)
            else:
                log(f"Failed to send Telegram notification. Status code: {response.status_code}, Response: {response.text}", log_id)
        except Exception as e:
            log(f"An error occurred while sending Telegram notification: {e}", log_id)
    else:
        log("Telegram bot token or chat ID not configured. Skipping notification.", log_id)


def get_product_info_from_rufus(driver, log_id, asin):
    ai_product_data = {}
    reply_sep = ' @@@@@@@@@ '
    request_mapping = {
        "brand" : "MARCA",
        "name" : "NOME DEL PRODOTTO",
        "description" : "DESCRIZIONE BREVE",
        "items_count" : "NUMERO ARTICOLI",
        "sold_by" :  "VENDUTO DA",
        "ships_from" :  "SPEDITO DA",
        "by_amazon" :  "VENDUTO E SPEDITO DA AMAZON YES/NO",
        "prime" : "DISPONIBILE CONSEGNA PRIME YES/NO"
    }
    for info, query in request_mapping.items():
        key = f"product_{info}_ai"
        ai_product_data[key] = None

    list_expected_replies = []
    for info, query in request_mapping.items():
        reply_format = f"{info} : <{query}>"
        list_expected_replies += [reply_format]

    full_request_query = f"rispondi con solo quello che ti chiedo e col formato '{reply_sep.join(list_expected_replies)}' rimpiazzando <...> con i valori relativi al prodotto. Non aggiungere altro testo",

    try:
        #log("Attempting to get info from RufusAI...", log_id)
        
        try:
            # Check if the RufusAI panel is visible
            WebDriverWait(driver, 2).until(
                EC.visibility_of_element_located((By.ID, "rufus-panel-header-minimize"))
            )
            #log("RufusAI panel is already visible.", log_id)
        except:
            # If not visible, click the button to open it
            #log("RufusAI panel not visible, trying to open it.", log_id)
            ask_button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//span[@data-action='dpx-rufus-connect']//button[contains(@class, 'ask-pill')]"))
            )
            ask_button.click()
            #log("Clicked the 'ask-pill' button to open RufusAI.", log_id)

        attempts = 0
        all_answer_texts = []
        answer_text = ""
        while reply_sep not in answer_text or answer_text.count(reply_sep) < len(request_mapping) - 1:
            attempts += 1
            if attempts > 3:
                joined_answer_texts = '\n> '.join(all_answer_texts)
                log(f"Could not get info from RufusAI! All replies follow:\n{joined_answer_texts}", log_id)
                break;

            # Wait for the text area to be visible before write the queries
            text_area = WebDriverWait(driver, 10).until(
                EC.visibility_of_element_located((By.ID, "rufus-text-area"))
            )

            text_area.send_keys(full_request_query)

            # Click the submit button
            submit_button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.ID, "rufus-submit-button"))
            )
            submit_button.click()

            # Wait for the answer element to be visible
            WebDriverWait(driver, 15).until(
                EC.visibility_of_element_located((By.XPATH, '(//div[@class="rufus-sections-container" and @data-section-class="TextSubsections"])[last()]//div[@role="region"]'))
            )
            # Wait for the text to be fully populated
            sleep(5)
            # Retrieve the answer by re-finding the element
            answer_text = driver.find_element(By.XPATH, '(//div[@class="rufus-sections-container" and @data-section-class="TextSubsections"])[last()]//div[@role="region"]').get_attribute("aria-label")
            #log(f"RufusAI reply (attempts #{attempts})> {answer_text}", log_id)

            all_answer_texts += [answer_text]

    except Exception as e:
        save_debug_html(driver, e, "rufus_ai", asin, log_id)
        log(f"Could not get info from RufusAI: {e}", log_id)

    else:
        for reply in answer_text.split(reply_sep):
            info, value = reply.split(' : ', 1)
            key = f"product_{info}_ai"
            ai_product_data[key] = value

    return ai_product_data

def get_all_offers(driver, asin, log_id):
    """
    Fetches and parses all offers for a given ASIN from the All Offers Display page.
    """
    log(f"Getting all offers for {asin} from AOD page.", log_id)
    aod_url = f"https://{amazon_host}/gp/product/ajax/aodAjaxMain?asin={asin}&pc=dp"
    driver.get(aod_url)
    WebDriverWait(driver, 30).until(
        lambda d: d.execute_script("return document.readyState == 'complete'")
    )

    offers = []

    def parse_offer(offer_element):
        offer_data = {}
        try:
            price_whole_str = offer_element.find_element(by=By.XPATH, value=".//span[contains(@class, 'a-price-whole')]").text.replace('.', '').replace(',', '')
            try:
                price_fraction_str = offer_element.find_element(by=By.XPATH, value=".//span[contains(@class, 'a-price-fraction')]").text
                offer_data['price'] = float(f"{price_whole_str}.{price_fraction_str}")
            except NoSuchElementException:
                offer_data['price'] = float(price_whole_str)

            try:
                offer_data['condition'] = offer_element.find_element(By.XPATH, ".//div[@id='aod-offer-heading']//span").text.strip()
            except NoSuchElementException:
                offer_data['condition'] = "N/A"
            
            offer_data['sold_by'] = "N/A"
            try:
                sold_by_element = offer_element.find_element(By.XPATH, ".//div[@id='aod-offer-soldBy']//a")
                offer_data['sold_by'] = sold_by_element.text.strip()
            except NoSuchElementException:
                pass

            offer_data['ships_from'] = "N/A"
            try:
                ships_from_element = offer_element.find_element(By.XPATH, ".//div[@id='aod-offer-shipsFrom']//span[@class='a-size-small a-color-base']")
                offer_data['ships_from'] = ships_from_element.text.strip()
            except NoSuchElementException:
                pass

        except Exception as e:
            log(f"Error parsing an offer: {e}", log_id)
            return None
        return offer_data

    # Pinned offer
    try:
        pinned_offer_element = driver.find_element(By.ID, "aod-pinned-offer")
        
        # Click "See more" to reveal seller and shipper info
        try:
            see_more_link = pinned_offer_element.find_element(By.ID, "aod-pinned-offer-show-more-link")
            see_more_link.click()
            WebDriverWait(driver, 5).until(
                EC.visibility_of_element_located((By.ID, "aod-pinned-offer-additional-content"))
            )
        except NoSuchElementException:
            pass # If "See more" is not present, continue

        pinned_offer_data = parse_offer(pinned_offer_element)
        if pinned_offer_data:
            pinned_offer_data['is_pinned'] = True
            offers.append(pinned_offer_data)
    except NoSuchElementException as e:
        log("No pinned offer found on AOD page.", log_id)
        save_debug_html(driver, e, "pinned_offer_not_found", asin, log_id)

    # Other offers
    try:
        offer_elements = driver.find_elements(By.XPATH, "//div[@id='aod-offer-list']//div[contains(@class, 'aod-information-block') and @role='listitem']")
        for offer_element in offer_elements:
            offer_data = parse_offer(offer_element)
            if offer_data:
                offer_data['is_pinned'] = False
                offers.append(offer_data)
    except NoSuchElementException:
        log("No other offers found on AOD page.", log_id)

    return offers

def scrape_product_data(driver, product_url, log_id, asin, use_rufus_ai=False):
    driver.get(product_url)
    WebDriverWait(driver, 30).until(
        lambda driver: driver.execute_script("return document.readyState == 'complete'")
    )
    handle_captcha(driver, log_id)

    scraped_data = {
        "product_name": "",
        "items_count": 1,
        "product_image_url": None,
        "current_price": -1.0,
        "delivery_cost": None,
        "sold_by": "N/A",
        "ships_from": "N/A",
        "condition_text": "N/A",
        "normalized_state": "unknown",
        "is_unavailable": False,
        "offer_container": None,
    }

    # Get product name
    try:
        scraped_data["product_name"] = driver.find_element(by=By.ID, value="productTitle").text.strip()
    except Exception as e:
        log(f"Could not find product name: {e}", log_id)

    # Get Sold by and Shipped by
    try:
        merchant_info_element = driver.find_element(by=By.ID, value="merchant-info")
        merchant_info_text = merchant_info_element.text

        sold_by_match = re.search(r"(?:Venduto da|Venditore|Sold by|Seller)\s*([^.|\n]+)", merchant_info_text)
        if sold_by_match:
            scraped_data["sold_by"] = sold_by_match.group(1).strip()

        ships_from_match = re.search(r"(?:Spedito da|Spedizione|Ships from|Shipped by)\s*([^.|\n]+)", merchant_info_text)
        if ships_from_match:
            scraped_data["ships_from"] = ships_from_match.group(1).strip()

    except NoSuchElementException:
        # Fallback to other XPaths if merchant-info is not found
        try:
            sold_by_element = driver.find_element(by=By.XPATH, value="//div[@tabular-attribute-name='Venduto da']//span")
            scraped_data["sold_by"] = sold_by_element.text.strip()
        except NoSuchElementException:
            pass # Sold by not found with this XPath

        try:
            ships_from_element = driver.find_element(by=By.XPATH, value="//div[@tabular-attribute-name='Spedito da']//span")
            scraped_data["ships_from"] = ships_from_element.text.strip()
        except NoSuchElementException:
            pass # Shipped by not found with this XPath
    except Exception as e:
        log(f"Could not find Sold by/Shipped by information: {e}", log_id)

    # Retrieve items count
    try:
        ITEMS_COUNT_XPATHS = [
            "//tr[contains(@class, 'po-number_of_items')]/td[2]/span",
            "//div[contains(@data-feature-name, 'metaData') and .//span[contains(text(), 'Numero di articoli')]]//span[@class='a-size-base a-color-tertiary']",
            "//div[contains(@data-feature-name, 'metaData') and .//span[contains(text(), 'Number of Items')]]//span[@class='a-size-base a-color-tertiary']",
            "//div[@id='detailBullets_feature_div']//span[contains(text(), 'Numero di articoli')]/following-sibling::span",
            "//div[@id='detailBullets_feature_div']//span[contains(text(), 'Number of Items')]/following-sibling::span"
        ]
        for xpath in ITEMS_COUNT_XPATHS:
            try:
                items_count_element = driver.find_element(by=By.XPATH, value=xpath)
                scraped_data["items_count"] = int(items_count_element.text)
                break  # if found, break the loop
            except (NoSuchElementException, ValueError):
                continue  # if not found, try the next xpath
    except Exception as e:
        log(f"Could not find or parse items count: {e}", log_id)
    
    # Try to find the product image URL
    try:
        IMAGE_XPATHS = [
            "//img[@id='landingImage']",
            "//img[@id='imgBlkFront']",
            "//div[contains(@class, 'imgTagWrapper')]/img"
        ]
        for xpath in IMAGE_XPATHS:
            try:
                image_element = driver.find_element(by=By.XPATH, value=xpath)
                scraped_data["product_image_url"] = image_element.get_attribute('src')
                if scraped_data["product_image_url"]:
                    break
            except NoSuchElementException:
                continue
    except Exception as e:
        log(f"Could not find product image: {e}", log_id)

    # Try to find the delivery cost
    try:
        delivery_cost_element = driver.find_element(by=By.XPATH, value="//div[@id='deliveryBlockMessage']//span[@data-csa-c-delivery-price]")
        delivery_cost_str = delivery_cost_element.get_attribute('data-csa-c-delivery-price')
        if delivery_cost_str:
            normalized_delivery_cost_str = delivery_cost_str.lower()
            if "senza costi aggiuntivi" in normalized_delivery_cost_str or "free" in normalized_delivery_cost_str:
                scraped_data["delivery_cost"] = 0.0
            else:
                match = re.search(r'(\d+,\d{2})', delivery_cost_str)
                if match:
                    cost_str = match.group(1).replace(',', '.')
                    scraped_data["delivery_cost"] = float(cost_str)
    except NoSuchElementException:
        pass # Delivery block is optional, so no error if not found
    except Exception as e:
        log(f"Could not parse delivery cost: {e}", log_id)

    # Check for product unavailability
    try:
        UNAVAILABLE_XPATHS = [
            "//div[@id='availability']//span[contains(text(), 'Attualmente non disponibile')]",
            "//div[@id='availability']//span[contains(text(), 'Currently unavailable')]",
            "//div[@id='availability']//span[contains(text(), 'Non disponibile')]",
            "//div[@id='outOfStock']",
        ]
        unavailable_element, _ = find_element_by_multiple_xpaths(driver, UNAVAILABLE_XPATHS, "unavailable element")
        if unavailable_element:
            scraped_data["is_unavailable"] = True
            scraped_data["current_price"] = -1.0
    except NoSuchElementException:
        pass

    # Check the main "Brand New" option (Featured Offer) only if not already determined as unavailable
    if not scraped_data["is_unavailable"]:
        try:
            MAIN_OFFER_CONTAINER_XPATHS = [
                "//div[@id='qualifiedBuybox']",
                "//div[@id='newAccordionRow_0']",
                "//div[@id='newAccordionRow_1']",
                "//div[@data-a-accordion-row-name='newAccordionRow']"
            ]
            offer_container, _ = find_element_by_multiple_xpaths(driver, MAIN_OFFER_CONTAINER_XPATHS, "main offer container")
            scraped_data["offer_container"] = offer_container

            price_whole_str = offer_container.find_element(by=By.XPATH, value=".//span[contains(@class, 'a-price-whole')]").text.replace('.', '').replace(',', '')
            try:
                price_fraction_str = offer_container.find_element(by=By.XPATH, value=".//span[contains(@class, 'a-price-fraction')]").text
                scraped_data["current_price"] = float(f"{price_whole_str}.{price_fraction_str}")
            except NoSuchElementException:
                scraped_data["current_price"] = float(price_whole_str)

            scraped_data["condition_text"] = "New"
            try:
                used_element = offer_container.find_element(by=By.XPATH, value=".//*[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'usato')] | .//*[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'used')] ")
                if used_element:
                    scraped_data["condition_text"] = used_element.text.strip()
            except NoSuchElementException:
                pass

            scraped_data["normalized_state"] = "new"
            condition_cleaned = scraped_data["condition_text"].lower()
            if "usato" in condition_cleaned or "used" in condition_cleaned:
                scraped_data["normalized_state"] = "used"
        except NoSuchElementException as e:
            save_debug_html(driver, e, "main_offer", asin, log_id)
        except Exception as e:
            save_debug_html(driver, e, "main_offer", asin, log_id)
            exc_type, exc_value, exc_tb = sys.exc_info()
            file_name = exc_tb.tb_frame.f_code.co_filename
            line_number = exc_tb.tb_lineno
            log(f"An unexpected error occurred while processing the main offer: {e} at file {file_name} line {line_number}", log_id)

    ai_product_data = {}
    if use_rufus_ai:
        # Get product info from RufusAI
        ai_product_data = get_product_info_from_rufus(driver, log_id, asin)

    return scraped_data | ai_product_data

def find_element_by_multiple_xpaths(driver, xpaths, description="element"):
    for xpath in xpaths:
        try:
            element = driver.find_element(by=By.XPATH, value=xpath)
            return element, xpath
        except NoSuchElementException:
            continue
    raise NoSuchElementException(f"Could not find {description} using any of the provided XPaths: {xpaths}")

def save_debug_html(driver, exception, context_name, asin, log_id):
    exc_type, exc_value, exc_tb = sys.exc_info()
    file_name = exc_tb.tb_frame.f_code.co_filename
    line_number = exc_tb.tb_lineno
    current_url = driver.current_url
    error_message = f"URL: {current_url}, File: {file_name}, Line: {line_number}, Error: {exception}"
    
    logs_dir = "logs"
    if not os.path.exists(logs_dir):
        os.makedirs(logs_dir)
        
    html_file_name = os.path.join(logs_dir, f"debug_{context_name}_not_found_{asin}.html")
    
    with open(html_file_name, "w", encoding="utf-8") as f:
        f.write(f"<!-- {error_message} -->\n")
        f.write(driver.page_source)
        
    log(f"Error during '{context_name}' processing. Page HTML saved to {html_file_name} for debugging. {error_message}", log_id)

def handle_captcha(driver, log_id):
    try:
        captcha_text_element = driver.find_element(by=By.XPATH, value="//h4[contains(text(), 'Fai clic sul pulsante qui sotto per continuare a fare acquisti')] | //h4[contains(text(), 'Type the characters you see in this image')] | //h4[contains(text(), 'Click the button below to continue shopping')] ")
        if captcha_text_element:
            log(f"CAPTCHA detected! Attempting to bypass by clicking 'Continue shopping' button.", log_id)
            random_delay = random.uniform(0, 3)
            log(f"Waiting for {random_delay:.2f} seconds before clicking 'Continue shopping' button.", log_id)
            sleep(random_delay)
            continue_button = driver.find_element(by=By.XPATH, value="//button[contains(text(), 'Continua con gli acquisti')] | //button[contains(text(), 'Continue shopping')] | //button[contains(text(), 'Continue with your order')] ")
            continue_button.click()
            log(f"'Continue shopping' button clicked. Waiting for 3 seconds.", log_id)
            sleep(3 + random.uniform(0, 3))
            return True # CAPTCHA was handled
    except NoSuchElementException:
        pass # No CAPTCHA
    return False # No CAPTCHA was found/handled

def generate_shortlink(driver, asin, log_id):
    shortlink = ""
    try:
        get_link_button = driver.find_element(by=By.CSS_SELECTOR, value="button[data-csa-c-content-id='sitestripe-get-linkbutton']")
        get_link_button.click()
        log(f"Clicked 'sitestripe-get-linkbutton' for {asin}", log_id)

        # Wait for the textarea to be populated
        wait = WebDriverWait(driver, 10)
        shortlink_textarea = wait.until(
            EC.presence_of_element_located((By.ID, "amzn-ss-text-shortlink-textarea"))
        )

        # Additional wait to ensure the value is not empty
        wait.until(
            lambda driver: shortlink_textarea.get_attribute("value") != ""
        )

        shortlink = shortlink_textarea.get_attribute("value")
        log(f"Generated shortlink for {asin}: {shortlink}", log_id)
    except Exception as e:
        log(f"Failed to generate shortlink for {asin}: {e}", log_id)
    return shortlink

def get_product_url(asin, seller_id=None):
    smid = sellers.get(seller_id, {}).get('smid') if seller_id else None
    if not smid and len(seller_id) in [13, 14] and seller_id.isalnum():
        smid = seller_id
    return f"https://{amazon_host}/dp/{asin}/?aod=0{f'&smid={smid}' if smid else ''}"

def get_affiliate_link(asin, amazon_tag, seller_id=None):
    smid = sellers.get(seller_id, {}).get('smid') if seller_id else None
    if not smid and len(seller_id) in [13, 14] and seller_id.isalnum():
        smid = seller_id
    return f"https://{amazon_host}/dp/{asin}/?offerta_selezionata_da={bot_name}{f'&smid={smid}' if smid else ''}&tag={amazon_tag}"


class pricesdrop_bot(threading.Thread):
    def __init__(self, amazon_host, amazon_tag, product, stop_event):
        self.amazon_host=amazon_host
        self.amazon_tag=amazon_tag
        self.product_name=product["name"]
        self.asin=product["asin"]
        self.cut_price=product["cut_price"]
        self.autoaddtocart=product.get("autoaddtocart", False)
        self.autocheckout=product.get("autocheckout", False)
        self.interval=product.get("interval", 5)
        self.seller_id=product.get("seller_id", "amazon")
        object_state=product.get("object_state")
        self.object_state = [state.lower() for state in object_state] if object_state else []
        self.previous_price = 0.0
        self.previous_offer_xpath = None
        self.stop_event = stop_event
        self.product_url = get_product_url(self.asin, self.seller_id)
        self.last_price = None
        self.last_check_time = None
        self.price_history = []
        self.history_file_path = os.path.join("data", f"{self.asin}_price_history.json")

        # Load price history from file if it exists
        if os.path.exists(self.history_file_path):
            try:
                with open(self.history_file_path, 'r', encoding='utf-8') as f:
                    loaded_history = json.load(f)
                    # Convert timestamps back to datetime objects
                    self.price_history = [(item[0], datetime.fromisoformat(item[1])) for item in loaded_history]
                    if self.price_history:
                        self.last_price = self.price_history[-1][0]
                        self.last_check_time = self.price_history[-1][1]
            except Exception as e:
                log(f"Error loading price history for {self.asin}: {e}", self.product_name)
        threading.Thread.__init__(self) 

    def _save_price_history(self):
        # Convert datetime objects to ISO format strings for JSON serialization
        serializable_history = [(item[0], item[1].isoformat()) for item in self.price_history]
        with open(self.history_file_path, 'w', encoding='utf-8') as f:
            json.dump(serializable_history, f, indent=4) 

    def run(self):
        driver = create_chrome_driver(headless=True) # Always headless for monitoring 

        # Always load cookies, as login is handled externally
        driver.get(f"https://{self.amazon_host}/")
        with open(".cookies.pkl", "rb") as f:
            cookies = pickle.load(f)
            for cookie in cookies:
                if 'domain' in cookie:
                    del cookie['domain']
                driver.add_cookie(cookie)
        driver.refresh()

        log_id = self.product_name

        log(f"Monitoring product '{self.product_name}' ({self.asin}) started", log_id)

        while True:
            sleep(self.interval + random.uniform(0, 3))
            if self.stop_event.is_set():
                break
            try:
                scraped_data = scrape_product_data(driver, self.product_url, log_id, self.asin)
                if self.stop_event.is_set():
                    break

                self.last_check_time = datetime.now()
                current_price = scraped_data["current_price"]
                if current_price > 0:
                    if self.last_price is None or current_price != self.last_price:
                        self.last_price = current_price
                        self.price_history.append((current_price, self.last_check_time))
                        self._save_price_history()

                product_image_url = scraped_data["product_image_url"]
                condition_text = scraped_data["condition_text"]
                normalized_state = scraped_data["normalized_state"]
                offer_container = scraped_data["offer_container"] # Keep for add to cart button
                delivery_cost = scraped_data["delivery_cost"]

                price_changed = current_price != self.previous_price

                if current_price == -1.0:
                    log_message = f"Monitored offer state: '{condition_text}' (normalized: '{normalized_state}'), price: UNAVAILABLE"
                elif current_price is None:
                    log_message = f"Monitored offer state: '{condition_text}' (normalized: '{normalized_state}'), price: ERROR_GETTING_PRICE"
                else:
                    log_message = f"Monitored offer state: '{condition_text}' (normalized: '{normalized_state}'), price: {current_price:.2f}"

                if current_price == -1.0:
                    if price_changed:
                        log(f"{log_message}", log_id)
                elif current_price is None:
                    if price_changed:
                        log(f"{log_message} - ERROR: unable to get main offer's current price...", log_id)
                elif self.object_state and normalized_state not in self.object_state:
                    if price_changed:
                        log(f"{log_message} - SKIPPING: State not in desired list {self.object_state}", log_id)
                elif current_price <= self.cut_price:
                    if price_changed:
                        log(f"{log_message} - ACCEPTED: Price is low enough.", log_id)

                        if self.autoaddtocart and not self.autocheckout:
                            try:
                                add_to_cart_button = offer_container.find_element(by=By.XPATH, value=".//input[@id='add-to-cart-button']")
                                add_to_cart_button.click()
                                log(f"!!! Just added to cart !!!", log_id)
                            except NoSuchElementException:
                                log(f"Could not find 'Add to Cart' button.", log_id)
                        elif self.autocheckout:
                            try:
                                add_to_cart_button = offer_container.find_element(by=By.XPATH, value=".//input[@id='add-to-cart-button']")
                                add_to_cart_button.click()
                                log(f"Added to cart, proceeding to checkout...", log_id)

                                # Go to cart page
                                driver.get(f"https://{self.amazon_host}/gp/cart/view.html")

                                # Wait for the checkout button to be clickable and then click it
                                checkout_button = WebDriverWait(driver, 10).until(
                                    EC.element_to_be_clickable((By.XPATH, '//*[@id="sc-buy-box-ptc-button"]/span/input'))
                                )
                                checkout_button.click()
                                log(f"Clicked 'Proceed to Checkout' button.", log_id)

                                # Wait for either the next button or the final order button to be clickable
                                wait = WebDriverWait(driver, 10)
                                element = wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="a-autoid-0-announce"] | //*[@id="submitOrderButtonId"]/span/input')))

                                # Check which element was found and click it
                                if element.tag_name == 'input':
                                    # This is the final order button
                                    element.click()
                                    log(f"!!! Successfully placed order !!!", log_id)
                                else:
                                    # This is the generic next button
                                    element.click()
                                    log(f"Clicked generic next button (a-autoid-0-announce).", log_id)
                                    # Now wait for the final button
                                    place_order_button = WebDriverWait(driver, 10).until(
                                        EC.element_to_be_clickable((By.XPATH, '//*[@id="submitOrderButtonId"]/span/input'))
                                    )
                                    place_order_button.click()
                                    log(f"!!! Successfully placed order !!!", log_id)

                                # After placing the order, the monitoring for this product should stop.
                                self.stop_event.set()

                            except NoSuchElementException as e:
                                log(f"Autocheckout failed: Could not find a required element. Error: {e}", log_id)
                            except Exception as e:
                                log(f"An unexpected error occurred during autocheckout: {e}", log_id)

                        shortlink = generate_shortlink(driver, self.asin, log_id)
                        if not shortlink:
                            shortlink = get_affiliate_link(self.asin, self.amazon_tag) # Fallback to full URL if shortlink generation fails
                    
                        message = f"{self.product_name} ({self.asin})"
                        message += f"\n📉 Il prezzo è crollato: {current_price:.2f} EUR!"
                        if delivery_cost is not None:
                            message += f"\n🚚 Consegna: {delivery_cost:.2f} EUR"
                        message += f"\nLink: {shortlink}"
                        send_telegram_notification(message, image_url=product_image_url, log_id=log_id)
                    
                else:
                    if price_changed:
                        log(f"{log_message} - SKIPPING: The current price is not low enough (i.e. > {self.cut_price:.2f})", log_id)
                
                # Update previous_price after all processing for the current iteration
                self.previous_price = current_price

                if self.stop_event.is_set(): # If main offer was processed and bought, exit
                    break

            except Exception as e:
                exc_type, exc_value, exc_tb = sys.exc_info()
                file_name = exc_tb.tb_frame.f_code.co_filename
                line_number = exc_tb.tb_lineno
                log(f"Error finding offers: {e} at file {file_name} line {line_number}", log_id)
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

def load_sellers_from_toml():
    sellers_file = 'sellers.toml'
    try:
        with open(sellers_file, 'r', encoding='utf-8') as f:
            sellers_toml = toml.load(f)
    except FileNotFoundError:
        log(f"'{sellers_file}' not found. Creating a default one.")
        with open(sellers_file, 'w', encoding='utf-8') as f:
            toml.dump({'amazon': {'name': 'Amazon', 'smid': 'A11IL2PNWYJU7H'}}, f)
        return {'amazon': {'name': 'Amazon', 'smid': 'A11IL2PNWYJU7H'}}
    return sellers_toml

def start_monitoring_product(product_data):
    asin = product_data['asin']
    if asin in active_threads:
        log(f"Product {asin} is already being monitored.")
        return

    log(f"Starting monitoring product '{product_data['name']}' ({asin}): {('buy it' if product_data.get('autocheckout') else ('add it to cart' if product_data.get('autoaddtocart') else 'notify it'))} if price drops under {product_data['cut_price']:.2f}...")
    stop_event = threading.Event()
    t = pricesdrop_bot(
        amazon_host=amazon_host, 
        amazon_tag=amazon_tag, 
        product=product_data,
        stop_event=stop_event
    )
    t.start()
    active_threads[asin] = {'thread': t, 'stop_event': stop_event, 'product_data': product_data}

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
        check_driver = create_chrome_driver(headless=True)
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
        login_driver = create_chrome_driver(headless=False)

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

    # Create data directory if it doesn't exist
    if not os.path.exists("data"):
        os.makedirs("data")

    for item in products:
        start_monitoring_product(item)

    # Signal that monitoring has started
    monitoring_started_event.set()
    log("Amazon monitoring initial setup complete. Telegram bot can now start.")


bot_name = os.getenv("TELEGRAM_BOT_NAME") or "pricesdrop.it"
bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
chat_id = os.getenv("TELEGRAM_CHAT_ID")

amazon_host=os.getenv("AMAZON_HOST") or "www.amazon.it"
amazon_tag=os.getenv("AMAZON_TAG") or "pricesdrop-21"
amazon_email=os.getenv("AMAZON_EMAIL")
amazon_psw=os.getenv("AMAZON_PASSWORD")


# Load products from TOML file
products = load_products_from_toml()
if products is None:
    sys.exit()

sellers = load_sellers_from_toml()

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
