
# Kuchlu Backend: In-Depth Documentation

This document provides a comprehensive technical guide to the Kuchlu backend API. It covers the architecture, core systems, and a detailed reference for every API endpoint.

## 1. Technical Architecture

The backend is a high-performance API built with Python and FastAPI, designed for real-time communication and scalability.

*   **Framework**: FastAPI for building robust, high-performance APIs with automatic OpenAPI documentation.
*   **Database**: Supabase (PostgreSQL) is used for data persistence. The backend communicates with it using the `supabase-py` client library. All data definition and management (DDL) is handled via SQL scripts in the `supabase/` directory.
*   **Real-Time & Scaling**: Redis is used as a message broker for a Pub/Sub system. This allows multiple, stateless backend instances to broadcast real-time events (like new messages or presence updates) to all connected clients, ensuring scalability.
*   **Authentication**: Secure JWT-based authentication with short-lived `access_token`s and long-lived `refresh_token`s for persistent sessions.
*   **File Storage**: Cloudinary is used for storing all user-uploaded media (avatars, images, documents, voice messages).
*   **Asynchronous Operations**: The entire backend is asynchronous (`async`/`await`) to handle high concurrency efficiently.

---

## 2. Core Systems Explained

### 2.1. Authentication Flow

The authentication system is designed for security and persistence.

1.  **Registration (`POST /auth/register`)**:
    *   A new user provides a phone number, password, and display name.
    *   The password is securely hashed using `bcrypt`.
    *   A new user record is created in the `users` table.

2.  **Login (`POST /auth/login`)**:
    *   The user provides their phone number and password.
    *   The server verifies the password against the stored hash.

3.  **Token Issuance**:
    *   Upon successful registration or login, the backend generates two JSON Web Tokens (JWTs):
        *   **`access_token`**: A short-lived token (e.g., 30 minutes) required to access protected API endpoints. It is sent in the `Authorization: Bearer <token>` header.
        *   **`refresh_token`**: A long-lived token (e.g., 7 days) used *only* to get a new `access_token`.

4.  **Token Refresh (`POST /auth/refresh`)**:
    *   When the `access_token` expires, the frontend sends the `refresh_token` to this endpoint.
    *   If the `refresh_token` is valid, the backend issues a *new* pair of access and refresh tokens. This is known as **token rotation** and enhances security.

5.  **Logout**:
    *   Logout is handled on the client-side by simply deleting the stored tokens. The server-side tokens will naturally expire.

### 2.2. Real-Time Event System

The real-time system is the heart of the application, designed for resilience and low latency.

1.  **Primary Connection (WebSocket - `/ws/connect`)**:
    *   The frontend first attempts to establish a WebSocket connection. This provides a low-latency, bidirectional communication channel for sending and receiving events instantly.
    *   Authentication is performed via a token in the query parameter (`?token=...`).

2.  **Fallback Connection (Server-Sent Events - `/events/subscribe`)**:
    *   If the WebSocket connection fails (e.g., due to a restrictive network proxy), the frontend automatically falls back to an SSE connection.
    *   SSE is a read-only channel where the server pushes events to the client.
    *   Actions from the client (like sending a message) are sent over standard HTTP POST requests to the API, which then broadcasts them to the recipient via Redis.

3.  **Event Broadcasting (Redis Pub/Sub)**:
    *   This is the key to scalability. When an event occurs (e.g., User A sends a message), the API instance that receives the request publishes the event to a central Redis channel.
    *   All other API instances are subscribed to this channel. They receive the event and forward it to their connected clients (either via WebSocket or SSE).

4.  **Event Sequencing & Sync (`GET /events/sync`)**:
    *   Every event broadcast through Redis is assigned a unique, sequential ID from a Redis counter. This sequence number is included in the event payload sent to the client.
    *   The client stores the `sequence` number of the last event it processed.
    *   If the client disconnects and reconnects, it calls `/events/sync?since=<last_sequence_id>`. The backend then fetches all events that have occurred since that number from a temporary event log (also in Redis) and sends them to the client, ensuring no messages are ever missed.

---

## 3. API Endpoint Reference

This section details every major API endpoint, its purpose, request format, and expected response.

### Auth Router (`/auth`)

#### `POST /register`
*   **Action**: Creates a new user account.
*   **Request Body**: `UserCreate` schema (`{ phone, password, display_name, email? }`)
*   **Success Response (200 OK)**: `Token` schema (`{ access_token, refresh_token, token_type, user: UserPublic }`)
*   **Error Responses**:
    *   **400 Bad Request**: If the phone number is already registered or validation fails.
    *   **500 Internal Server Error**: If the database operation fails.

#### `POST /login`
*   **Action**: Authenticates a user and issues tokens.
*   **Request Body**: `OAuth2PasswordRequestForm` (`{ username: phone, password }`)
*   **Success Response (200 OK)**: `Token` schema.
*   **Error Responses**:
    *   **401 Unauthorized**: If credentials are incorrect.

#### `POST /refresh`
*   **Action**: Issues a new `access_token` using a valid `refresh_token`.
*   **Request Headers**: `Authorization: Bearer <refresh_token>`
*   **Success Response (200 OK)**: `Token` schema with a new `access_token` and a new `refresh_token`.
*   **Error Responses**:
    *   **401 Unauthorized**: If the refresh token is invalid, expired, or not provided.

### User Router (`/users`)

#### `GET /me`
*   **Action**: Retrieves the profile of the currently authenticated user.
*   **Success Response (200 OK)**: `UserPublic` schema.

#### `PUT /me/profile`
*   **Action**: Updates the authenticated user's profile (e.g., display name, mood).
*   **Request Body**: `UserUpdate` schema (`{ display_name?, mood?, email? }`)
*   **Success Response (200 OK)**: The updated `UserPublic` schema.
*   **Events Broadcast**: `user_profile_update` to the user's partner.

#### `POST /me/avatar`
*   **Action**: Uploads a new avatar image for the user.
*   **Request Body**: `multipart/form-data` with a `file` field.
*   **Success Response (200 OK)**: The updated `UserPublic` schema with the new `avatar_url`.
*   **Events Broadcast**: `user_profile_update` (with new `avatar_url`) to the user's partner.

### Partner Router (`/partners`)

#### `POST /request`
*   **Action**: Sends a partnership request to another user.
*   **Request Body**: `{ "recipient_id": "uuid" }`
*   **Success Response (200 OK)**: `PartnerRequestResponse` schema containing details of the created request.
*   **Error Responses**:
    *   **400 Bad Request**: If the user is already in a partnership or a request already exists.

#### `POST /requests/{request_id}/respond`
*   **Action**: Accepts or rejects an incoming partner request.
*   **Request Body**: `{ "action": "accept" | "reject" }`
*   **Success Response (204 No Content)**: An empty response.
*   **Side Effect**: If accepted, establishes the partner link for both users.

### Chat Router (`/chats`)

#### `POST /`
*   **Action**: Creates a new chat with the user's partner or retrieves the existing one.
*   **Request Body**: `{ "recipient_id": "partner_uuid" }`
*   **Success Response (200 OK)**: `ChatResponse` schema.
*   **Error Responses**:
    *   **403 Forbidden**: If the `recipient_id` is not the user's partner.

#### `GET /{chat_id}/messages`
*   **Action**: Retrieves a paginated list of messages for a chat.
*   **Query Parameters**: `?limit=50&before_timestamp=<iso_date_string>`
*   **Success Response (200 OK)**: `MessageListResponse` schema (`{ messages: [MessageInDB] }`).

#### `POST /{chat_id}/messages`
*   **Action**: Sends a message in a chat (used as a fallback for SSE clients).
*   **Request Body**: `MessageCreate` schema.
*   **Success Response (200 OK)**: The created `MessageInDB` object.
*   **Events Broadcast**: `new_message` to all chat participants.

### WebSocket Events (`/ws/connect`)

The WebSocket connection is the primary real-time communication channel.

#### Client-to-Server Events
*   `send_message`: Sends a chat message. Payload matches `MessageCreate` schema.
*   `toggle_reaction`: Adds or removes an emoji reaction from a message. Payload: `{ message_id, chat_id, emoji }`.
*   `start_typing` / `stop_typing`: Informs the server about the user's typing status. Payload: `{ chat_id }`.
*   `ping_thinking_of_you`: Sends a "thinking of you" ping. Payload: `{ recipient_user_id }`.
*   `change_chat_mode`: Switches the chat mode. Payload: `{ chat_id, mode: "normal" | "fight" | "incognito" }`.
*   `HEARTBEAT`: A keep-alive signal sent by the client.

#### Server-to-Client Events
*   `new_message`: A new message has been posted in a chat.
*   `message_reaction_update`: A message's reactions have been updated.
*   `user_presence_update`: A user's online status or mood has changed.
*   `typing_indicator`: A user has started or stopped typing.
*   `thinking_of_you_received`: The user has received a "thinking of you" ping.
*   `user_profile_update`: A user's profile (name, avatar) has been updated.
*   `message_ack`: Confirms that a message sent by the client has been processed by the server.
*   `chat_mode_changed`: Notifies clients that the chat mode has changed.
*   `error`: Reports a server-side error related to a client action.

---

## 4. Developer Setup

### 4.1. Environment Variables
Create a `.env` file in this directory (`kuchlu-backend`) and populate it with the required keys from `.env.example`.

### 4.2. Running the Application
1.  Install dependencies: `pip install -r requirements.txt`
2.  Run the development server: `uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload`

### 4.3. Initial Data Seeding
To populate your database with the default sticker packs, copy the content of `supabase/seed_stickers.sql` and run it in the SQL Editor in your Supabase project dashboard.
