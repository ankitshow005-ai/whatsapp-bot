# 🤖 Fynlo WhatsApp AI Sales & Booking Bot

An AI-powered WhatsApp assistant for **Fynlo** that answers customer questions, provides sales guidance, books real calendar meetings, manages bookings, and escalates conversations to a human only when truly necessary.

---

# The Big Idea

Most WhatsApp chatbots are just keyword matchers or FAQ bots.

This project takes a different approach.

Instead of having separate classifiers, FAQ bots, sales bots, and booking bots, **every incoming WhatsApp message goes through a single AI reasoning step**.

The AI understands:

- What the user wants
- Whether it can answer
- Whether a meeting is actually needed
- Whether a human should be involved

The goal is simple:

> **Never ask a human if the AI can solve it. Never ask the customer for information twice.**

---

# High Level Architecture

```
                 WhatsApp User
                        │
                        ▼
                  Twilio Webhook
                        │
                        ▼
                 FastAPI (main.py)
                        │
                        ▼
               Single LLM Reasoning
                        │
        ┌───────────────┼────────────────┐
        │               │                │
        ▼               ▼                ▼
     Answer FAQ     Book Meeting     Escalate
        │               │
        │          TidyCal API
        │
        ▼
   WhatsApp Reply
```

---

# Features

- AI-powered FAQ assistant
- AI sales advisor
- Live calendar booking
- Reschedule meetings
- Cancel meetings
- Conversation memory
- Product knowledge base
- WhatsApp integration using Twilio
- Human escalation only when required

---

# 📂 Project Structure

| File | Purpose |
|------|---------|
| **main.py** | The heart of the application. Receives WhatsApp messages, asks the LLM to understand the user's intent, and routes the conversation. |
| **state.py** | Stores conversation history, booking progress, last customer details, and booking IDs so users don't have to repeat themselves. |
| **booking.py** | Handles the complete booking workflow including collecting customer details, booking meetings, suggesting alternative slots, cancellation, and rescheduling. |
| **tidycal_api.py** | Wrapper around the TidyCal REST API. Checks live availability, creates bookings, cancels bookings, and reschedules meetings. |
| **knowledge_base.py** | Contains all Fynlo product knowledge. Updating this file updates the bot's knowledge without changing application code. |
| **time_parser.py** | Converts natural language like "tomorrow 3pm" or "Friday morning" into a valid datetime. |
| **llm.py** | One simple interface for interacting with the configured LLM provider (Gemini, Groq, OpenAI, or Qwen). |
| **config.py** | Loads all environment variables and project configuration. |
| **test_chat.py** | Lets you test the chatbot locally without WhatsApp or Twilio. |
| **requirements.txt** | Python dependencies required to run the project. |

---

# How a Message is Processed

Whenever a user sends a WhatsApp message:

```
User
 │
 ▼
Twilio receives message
 │
 ▼
FastAPI webhook
 │
 ▼
Conversation history loaded
 │
 ▼
Single LLM call
 │
 ▼
Returns JSON
```

Example:

```json
{
  "intent": "answer",
  "reply": "Yes, Fynlo integrates with Tally."
}
```

Possible intents:

- answer
- book
- manage_booking
- escalate
- out_of_domain

The application then executes the appropriate workflow.

---

# Knowledge Base

Unlike many chatbots that hardcode answers throughout the project, **all product information lives in one place.**

```
knowledge_base.py
```

It contains information about:

- Features
- Pricing
- Plans
- Integrations
- Supported file types
- FAQs
- Sales guidance
- Objection handling

If the product changes, simply update the knowledge base.

No Python code needs to change.

---

# Conversation Memory

WhatsApp itself is stateless.

The bot maintains memory using `state.py`.

It remembers:

- Conversation history
- Current booking step
- Customer name
- Customer email
- Last booking ID

This allows conversations like:

```
User:
Reschedule my meeting

Bot:
Sure! Using your previous details.
What time would you like instead?
```

Instead of asking:

- What's your name?
- What's your email?

again.

---

# Booking Flow

Unlike many bots that immediately ask for personal information, this bot first understands **why** the customer wants a meeting.

```
User
 │
 ▼
"I want to book a demo."
 │
 ▼
"What would you like help with?"
 │
 ▼
Can AI answer?
 │
 ├───────────────┐
 │               │
 ▼               ▼
Yes             No
 │               │
Answer       Continue booking
```

If a meeting is still needed:

```
Collect Name
      │
Collect Email
      │
Collect Preferred Time
      │
Check Live Calendar
      │
Book Meeting
```

---

# Live Calendar Integration

The chatbot doesn't guess availability.

It connects directly to **TidyCal**.

It can:

- Check live availability
- Book meetings
- Suggest alternative slots
- Cancel meetings
- Reschedule meetings

If the requested slot isn't available, the bot automatically suggests real open slots.

---

# Natural Language Time Parsing

Users don't need to follow a strict format.

Examples:

```
Tomorrow at 3

Friday Morning

Next Monday after lunch

Thursday 2pm
```

The parser works in two steps.

## Step 1

Use `dateparser`.

Fast.

Free.

No LLM call.

## Step 2

If parsing fails:

```
LLM

↓

Normalizes the text

↓

dateparser retries
```

This makes the system both accurate and inexpensive.

---

# Human Escalation

The founder is only notified when the AI genuinely shouldn't answer.

Examples:

- Refund requests
- Enterprise negotiations
- Partnerships
- Technical bugs
- Billing disputes

When escalation happens, the founder receives:

- Customer phone number
- Conversation summary
- Full conversation context

This means nobody has to ask:

> "Sorry, what happened?"

---

# Configuration

Create a `.env` file.

```env
# Twilio
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_WHATSAPP_FROM=
OWNER_WHATSAPP_NUMBER=

# LLM
LLM_PROVIDER=gemini

GEMINI_API_KEY=
GROQ_API_KEY=
OPENAI_API_KEY=
QWEN_API_KEY=

# TidyCal
TIDYCAL_API_KEY=
TIDYCAL_BOOKING_TYPE_ID=
TIDYCAL_TIMEZONE=Asia/Kolkata
```

Changing the AI provider requires changing only one line:

```env
LLM_PROVIDER=groq
```

No code changes are required.

---

# Running the Project

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the server:

```bash
uvicorn main:app --reload --port 8001
```

Expose it using ngrok (or any tunnel):

```bash
ngrok http 8001
```

Point your Twilio webhook to:

```
https://your-domain.com/whatsapp/webhook
```

---

# Local Testing

You don't need WhatsApp during development.

Run:

```bash
python test_chat.py
```

This opens a terminal chat that sends requests directly to the FastAPI application, making development much faster.

---

# Future Improvements

- Database-backed conversation memory
- User authentication
- CRM integration
- Analytics dashboard
- RAG using vector databases
- Multi-language support
- Multi-agent architecture
- Admin dashboard
- Voice message support

---

# Why This Project?

This project demonstrates how a modern LLM-powered conversational system can combine:

- Product knowledge
- Sales reasoning
- Live calendar automation
- Conversation memory
- Human escalation

into a single natural WhatsApp experience.

Instead of behaving like a traditional chatbot, it behaves like a knowledgeable sales representative that understands context, remembers users, and automates the entire customer journey.