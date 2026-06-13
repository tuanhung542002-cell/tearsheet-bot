"""
Tearsheet Bot — Telegram bot that looks up a company on FiinGate/Vietstock
and returns a PDF tearsheet.

Usage (on Telegram):
  Kingfoodmart
  MSN public
  Masan private
"""

import logging
import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from lookup import run_lookup

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO
)
log = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
ALLOWED_CHAT_IDS = os.environ.get("ALLOWED_CHAT_IDS", "")  # comma-separated, leave blank to allow all


def is_allowed(chat_id: int) -> bool:
    if not ALLOWED_CHAT_IDS.strip():
        return True
    return str(chat_id) in [x.strip() for x in ALLOWED_CHAT_IDS.split(",")]


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Tearsheet Bot*\n\n"
        "Send me a company name and I'll pull financials from FiinGate / Vietstock "
        "and return a PDF tearsheet.\n\n"
        "*Examples:*\n"
        "• `Kingfoodmart`\n"
        "• `MSN public`\n"
        "• `Masan private`\n"
        "• `VNM`\n\n"
        "Add `public` or `private` to override auto-detection.",
        parse_mode="Markdown"
    )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await cmd_start(update, ctx)


async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    if not is_allowed(chat_id):
        await update.message.reply_text("⛔ Unauthorized.")
        return

    query = update.message.text.strip()
    if not query:
        return

    log.info(f"[{chat_id}] Query: {query}")
    status_msg = await update.message.reply_text(f"🔍 Looking up *{query}*...", parse_mode="Markdown")

    try:
        pdf_path, company_name, source, note = await run_lookup(
            query=query,
            status_callback=lambda msg: ctx.bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_msg.message_id,
                text=msg,
                parse_mode="Markdown"
            )
        )

        await ctx.bot.edit_message_text(
            chat_id=chat_id,
            message_id=status_msg.message_id,
            text=f"✅ *{company_name}* — tearsheet ready",
            parse_mode="Markdown"
        )

        caption = f"📊 *{company_name}*\nSource: {source}"
        if note:
            caption += f"\n_{note}_"

        with open(pdf_path, "rb") as f:
            await ctx.bot.send_document(
                chat_id=chat_id,
                document=f,
                filename=f"{company_name} Tearsheet.pdf",
                caption=caption,
                parse_mode="Markdown"
            )

    except Exception as e:
        log.exception(f"Lookup failed for '{query}'")
        await ctx.bot.edit_message_text(
            chat_id=chat_id,
            message_id=status_msg.message_id,
            text=f"❌ Could not generate tearsheet for *{query}*.\n\nError: `{str(e)[:200]}`",
            parse_mode="Markdown"
        )


def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    log.info("Bot started — polling...")
    app.run_polling()


if __name__ == "__main__":
    main()
