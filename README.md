# Fynlo WhatsApp AI Sales & Booking Bot

An AI-powered WhatsApp assistant for **Fynlo** that answers customer questions, provides sales guidance, books real calendar meetings, manages bookings, and escalates conversations to a human only when truly necessary.

---

# The Big Idea

Most WhatsApp chatbots are built around multiple independent components such as classifiers, FAQ bots, sales bots, and booking bots.

This project takes a different approach.

Every incoming WhatsApp message goes through a **single AI reasoning step** that understands:

- What the customer wants
- Whether the AI can answer it
- Whether a meeting is actually required
- Whether the conversation should be escalated to a human

The goal is simple:

> **Never ask a human if the AI can solve it. Never ask the customer for information twice.**

---

# Tech Stack

| Category | Technology |
|----------|------------|
| Language | Python |
| Backend | FastAPI |
| AI Models | Gemini, Groq, OpenAI, Qwen |
| Messaging | Twilio WhatsApp API |
| Calendar | TidyCal API |
| Natural Language Time Parsing | dateparser |
| Configuration | python-dotenv |
| HTTP Client | requests |
| Local Testing | test_chat.py |

---

# High Level Architecture

```text
Incoming WhatsApp message
        │
        ▼
Is a booking already in progress for this user?
        │
   ┌────┴─────┐
  YES         NO
   │           │
   ▼           ▼
Continue    classify_message() picks ONE:
booking          │
step        ┌────┼─────────┬──────────┬────────────┐
             ▼    ▼         ▼          ▼            ▼
         greeting faq  sales_advice booking_intent complex
             │     │        │            │            │
          say hi  answer  give advice  START a     escalate to
                  from KB  (persuasive)  booking     founder with
                                         flow →       FULL history
                                       booking.py
```

---

# Features

- AI-powered FAQ assistant
- AI sales advisor
- Live calendar booking
- Meeting rescheduling
- Meeting cancellation
- Conversation memory
- Product knowledge base
- Twilio WhatsApp integration
- Human escalation only when required
- Configurable LLM provider (Gemini, Groq, OpenAI, Qwen)

---

# Project Structure

| File | Purpose |
|------|---------|
| **main.py** | Main FastAPI application. Receives incoming WhatsApp webhooks, manages conversation state, classifies user intent, and routes the request. |
| **state.py** | Stores conversation history, booking progress, remembered customer details, and booking IDs. |
| **booking.py** | Handles the complete booking workflow including collecting user details, booking meetings, suggesting alternatives, cancellation, and rescheduling. |
| **tidycal_api.py** | Wrapper around the TidyCal REST API for checking availability and managing bookings. |
| **knowledge_base.py** | Centralized product knowledge used to answer factual and sales-related questions. |
| **time_parser.py** | Converts natural language dates into structured datetime objects. |
| **llm.py** | Unified interface for interacting with the configured LLM provider. |
| **config.py** | Loads configuration and API keys from environment variables. |
| **test_chat.py** | Local CLI application for testing the chatbot without WhatsApp. |
| **requirements.txt** | Python dependencies. |

---

# Message Processing Flow

Every WhatsApp message follows the same processing pipeline.

1. Twilio receives the incoming WhatsApp message.
2. Twilio forwards it to the FastAPI webhook.
3. Previous conversation history is loaded from memory.
4. The latest message and history are sent to the LLM.
5. The LLM determines the user's intent.
6. The application executes the appropriate workflow.
7. The response is sent back through Twilio.

Example response from the LLM:

```json
{
    "intent": "answer",
    "reply": "Yes, Fynlo integrates with Tally."
}
```

Supported intents include:

- greeting
- faq
- sales_advice
- booking_intent
- booking_management
- complex
- out_of_domain

---

# Knowledge Base

Instead of hardcoding answers throughout the project, all product information is stored in a single file.

```
knowledge_base.py
```

It contains:

- Product features
- Pricing
- Plans
- Integrations
- Frequently asked questions
- Sales information
- Objection handling

Updating the product knowledge requires editing only this file.

No application logic needs to change.

---

# Conversation Memory

WhatsApp conversations are stateless.

The application maintains conversation state using `state.py`.

The following information is stored per user:

- Conversation history
- Current booking stage
- Customer name
- Customer email
- Last confirmed booking ID

This allows conversations like:

```text
User:
Reschedule my meeting

Bot:
Sure.
What time would you like instead?
```

instead of repeatedly asking for customer details.

---

# Booking Flow

The chatbot does not immediately ask for personal information.

Instead, it first determines why the customer wants a meeting.

```text
User
 │
 ▼
"I'd like to schedule a demo."
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

If a meeting is still required, the booking workflow continues:

```text
Collect Name
      │
Collect Email
      │
Collect Preferred Time
      │
Check Live Availability
      │
Create Booking
```

---

# Live Calendar Integration

The chatbot communicates directly with the TidyCal API.

It supports:

- Checking live availability
- Creating bookings
- Suggesting alternative time slots
- Cancelling bookings
- Rescheduling bookings

If a requested slot is unavailable, the application automatically recommends available alternatives.

---

# Natural Language Time Parsing

Users can enter dates naturally.

Examples:

```text
Tomorrow at 3 PM

Friday Morning

Next Monday after lunch

Thursday 2 PM
```

The parser works in two stages.

### Stage 1

Use the `dateparser` library.

- Fast
- Local
- No LLM call required

### Stage 2

If parsing fails:

```text
LLM
        │
        ▼
Normalize Date Expression
        │
        ▼
Retry dateparser
```

This reduces API usage while maintaining accuracy.

---

# Human Escalation

The founder is contacted only when AI should not respond automatically.

Typical examples include:

- Refund requests
- Enterprise negotiations
- Partnerships
- Technical issues
- Billing disputes

Each escalation includes:

- Customer phone number
- Conversation summary
- Complete conversation history

This gives the human operator full context before responding.

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

Changing the LLM provider only requires changing:

```env
LLM_PROVIDER=groq
```

No code modifications are required.

---

# Running the Project

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the FastAPI server:

```bash
uvicorn main:app --reload --port 8001
```

Expose the application:

```bash
ngrok http 8001
```

Configure the Twilio WhatsApp webhook:

```text
https://your-domain.com/whatsapp/webhook
```

---

# Local Testing

The chatbot can be tested without Twilio.

Run:

```bash
python test_chat.py
```

This opens a terminal interface that communicates directly with the chatbot logic.

---

# Future Improvements

- Persistent database-backed memory
- CRM integration
- Analytics dashboard
- Retrieval-Augmented Generation (RAG)
- Voice message support
- Multi-language conversations
- Admin dashboard
- Multi-agent architecture
- User authentication

---

# Why This Project?

This project demonstrates how an LLM-powered conversational assistant can combine:

- Product knowledge
- Sales reasoning
- Live calendar scheduling
- Conversation memory
- Human escalation

into a single WhatsApp experience.

Rather than behaving like a rule-based chatbot, it behaves like an AI sales representative capable of understanding context, maintaining conversations, automating scheduling, and escalating only when necessary.