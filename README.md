<div align="center">
  <img src="https://raw.githubusercontent.com/brushtyler/pricesdropbot/main/docs/logo.png" alt="PricesDropBot Logo" width="200">
  <h1>PricesDropBot</h1>
  <p>
    <b>A sophisticated Amazon price monitoring bot with automated purchasing capabilities and a powerful Telegram interface.</b>
  </p>
  <p>
    <a href="https://github.com/brushtyler/pricesdropbot/blob/main/LICENSE"><img src="https://img.shields.io/github/license/brushtyler/pricesdropbot" alt="License"></a>
    <a href="https://github.com/brushtyler/pricesdropbot/issues"><img src="https://img.shields.io/github/issues/brushtyler/pricesdropbot" alt="Issues"></a>
  </p>
</div>

PricesDropBot is a Python-based tool that automates tracking Amazon product prices. It can notify you, add items to your cart, or even purchase them for you when the price drops below a specified threshold. Manage it all on the go with a full-featured Telegram bot.

This project was originally inspired by [AmazonAutoBuyBot](https://github.com/davildf/Amazonautobuybot) but has been completely rewritten to offer a more robust, feature-rich, and user-friendly experience.

## Table of Contents

- [Features](#features)
- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Installation](#installation)
- [Configuration](#configuration)
  - [Environment Variables (`.env`)](#environment-variables-env)
  - [Products (`products.toml`)](#products-productstoml)
  - [Sellers (`sellers.toml`)](#sellers-sellerstoml)
- [Usage](#usage)
- [How It Works](#how-it-works)
- [Telegram Bot Commands](#telegram-bot-commands)
- [Troubleshooting](#troubleshooting)
- [License](#license)

## Features

- **Intelligent Price Monitoring**: Continuously tracks prices for your chosen products.
- **Flexible Automation**: Automatically purchase, add to cart, or just get notified.
- **Multi-Seller Support**: Monitor offers from Amazon or specific third-party sellers.
- **Advanced Scraping**: Uses Selenium with CAPTCHA handling and RufusAI integration for enhanced data retrieval.
- **Interactive Telegram Bot**: Add, remove, list, and get detailed info about products on the fly.
- **Persistent Sessions**: Cookie-based session management minimizes the need for repeated logins and 2FA.
- **Dynamic Configuration**: Reload products and settings without restarting the bot.
- **Detailed History**: Keeps a local JSON history of price changes for each product.
- **Debug Tools**: Saves HTML snapshots and provides detailed logs for easier troubleshooting.

## Getting Started

### Prerequisites

- Python 3.8+
- Google Chrome and [ChromeDriver](https://googlechromelabs.github.io/chrome-for-testing/)
  - The script will try to use `selenium-manager` to download ChromeDriver if it's not in your `PATH`.
- A Telegram Bot Token and your Chat ID.

### Installation

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/brushtyler/pricesdropbot.git
    cd pricesdropbot
    ```

2.  **Create and activate a virtual environment:**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    # On Windows, use: venv\Scripts\activate
    ```

3.  **Install the required dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

## Configuration

### Environment Variables (`.env`)

Create a `.env` file in the project root. You can copy `.env.sample` to get started.

```env
# The Amazon domain to use (e.g., www.amazon.com, www.amazon.co.uk)
AMAZON_HOST="www.amazon.it"

# Your Amazon affiliate tag (optional, for generating affiliate links)
AMAZON_TAG="your-tag-21"

# Your Amazon login credentials
AMAZON_EMAIL="your-amazon-email@example.com"
AMAZON_PASSWORD="your-amazon-password"

# Your Telegram bot's token from BotFather
TELEGRAM_BOT_TOKEN="your-telegram-bot-token"

# Your personal Telegram Chat ID (you can get it from @userinfobot)
TELEGRAM_CHAT_ID="your-telegram-chat-id"

# A name for your bot, used in generated affiliate links
TELEGRAM_BOT_NAME="pricesdrop.it"
```

### Products (`products.toml`)

Create a `products.toml` file to list the items you want to monitor. Copy `products.sample.toml` to begin.

Each product is a TOML table. Here is an example with all available options:

```toml
["Example Product Name"]
# Required fields
asin = "B08H93ZRK9"      # The product's Amazon Standard Identification Number.
cut_price = 350.00       # The price threshold to trigger actions.

# Optional fields
enabled = true           # Set to false to temporarily disable monitoring for this product.
autoaddtocart = false    # If true, adds the product to the cart when the price is right.
autocheckout = false     # If true, attempts to purchase the item. (Use with caution!)
interval = 300           # Seconds between price checks for this item (default: 60).
seller_id = "amazon"     # ID of the seller to monitor. See sellers.toml. Defaults to "amazon".

# Monitor only specific product conditions.
# Valid states: "new", "used-like new", "used-very good", "used-good", "used-acceptable"
object_state = ["new", "used-like new"]
```

### Sellers (`sellers.toml`)

This file maps human-readable `seller_id`s to Amazon's `smid` (seller merchant ID). You can find the `smid` in the URL when viewing a seller's page.

A default `sellers.toml` is created if one doesn't exist.

```toml
[amazon]
name = "Amazon"
smid = "A11IL2PNWYJU7H" # Example for Amazon.it, this may vary by region

[another-seller]
name = "Another Seller Name"
smid = "A123BCDEFG45HI"
```

## Usage

Once configured, run the bot:

```bash
python3 main.py
```

On the first run, you may need to complete a login and 2FA process in the browser window that opens. The bot will then save your session cookies to `.cookies.pkl` to streamline future logins.

## How It Works

The bot launches a main thread to manage the Amazon monitoring process and another for the Telegram bot.

1.  **Login**: It first checks for valid session cookies. If they are missing or expired, it opens a non-headless Chrome browser for you to log in.
2.  **Monitoring Threads**: For each enabled product in `products.toml`, a separate monitoring thread is started.
3.  **Scraping**: Each thread periodically opens the product page, handles potential CAPTCHAs, and scrapes price, availability, and seller information.
4.  **Action**: If the price is below `cut_price` and the conditions (`object_state`, `seller_id`) are met, it triggers the configured action (notify, add to cart, or checkout).
5.  **History**: All price changes are logged to a JSON file in the `data/` directory for each product.

## Telegram Bot Commands

- `/start`: Displays a welcome message.
- `/add <ASIN>`: Interactively add a new product to the monitoring list.
- `/delete <ASIN>`: Stop monitoring and remove a product.
- `/list`: Show all products currently being monitored.
- `/info <ASIN>`: Get detailed monitoring data for a product, including price history.
- `/reload`: Reloads the `products.toml` file, adding, removing, and updating products without a restart.
- `/post <ASIN> <seller_id> <message>`: Creates and sends a custom Telegram notification for a product.
- `/get <ASIN> <seller_id> [options]`: Fetches and displays extensive product data from both the DOM and RufusAI. Use `debug` in options to run in non-headless mode.
- `/offers <ASIN> [options]`: Retrieves all available offers for a product from the "All Offers Display" page.
- `/cancel`: Cancels an ongoing conversation (like adding a product).

## Troubleshooting

- **Login Issues**: If the bot gets stuck at login, delete the `.cookies.pkl` file and restart it to force a fresh login.
- **CAPTCHAs**: The bot has basic CAPTCHA handling, but if it fails repeatedly, you may need to solve it manually in the browser. Running in non-headless mode can help.
- **"Element Not Found" Errors**: Amazon frequently changes its page layout. This can cause scraping to fail. The bot saves a `debug_*.html` file in the `logs/` directory when this happens. Please open an issue with this file to help us update the selectors.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.