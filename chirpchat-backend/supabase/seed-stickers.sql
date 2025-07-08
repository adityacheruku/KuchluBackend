-- =================================================================
-- CHIRPCHAT STICKER & EMOJI SEEDING SCRIPT
-- =================================================================
-- To use this script:
-- 1. Fill in your own data in the "INSERT YOUR DATA" sections below.
-- 2. Go to your Supabase project dashboard.
-- 3. In the left sidebar, click on the "SQL Editor" icon.
-- 4. Click "+ New query".
-- 5. Paste the entire content of this file into the editor.
-- 6. Click the "RUN" button.
-- =================================================================

-- Step 1: Clear all existing sticker and emoji data for a fresh start.
-- This ensures no old data conflicts with your new data.
TRUNCATE TABLE user_favorite_stickers RESTART IDENTITY;
TRUNCATE TABLE user_sticker_usage RESTART IDENTITY;
TRUNCATE TABLE stickers RESTART IDENTITY CASCADE;
TRUNCATE TABLE sticker_packs RESTART IDENTITY CASCADE;

RAISE NOTICE 'All existing sticker data has been cleared.';

-- =================================================================
-- INSERT YOUR DATA BELOW
-- =================================================================

-- Step 2: Define your Sticker Packs.
-- Replace the example values with your own pack details.
-- You can add multiple packs by adding more lines inside the VALUES clause.
-- Example: VALUES (uuid_generate_v4(), 'My First Pack', ...), (uuid_generate_v4(), 'My Second Pack', ...);
INSERT INTO "sticker_packs" (id, name, description, thumbnail_url, is_premium, is_active) VALUES
(
  'f47ac10b-58cc-4372-a567-0e02b2c3d479', -- You can generate a UUID or use a memorable one.
  'Greetings', -- The name of your sticker pack.
  'A collection of friendly greetings.', -- A short description.
  'https://res.cloudinary.com/your-cloud/image/upload/v1/your-pack-thumbnail.png', -- URL to a thumbnail image for the pack.
  false, -- `false` for free, `true` for premium.
  true -- `true` to make it visible in the app.
);

-- You can add more packs like this:
-- INSERT INTO "sticker_packs" (id, name, description, thumbnail_url, is_premium, is_active) VALUES
-- ('another-uuid-here', 'Another Pack', 'Description here', 'https://example.com/thumb2.png', false, true);


-- Step 3: Define the Stickers for each pack.
-- Make sure the `pack_id` matches the `id` of the pack you created above.
-- Add all your stickers for a pack inside the VALUES clause.
INSERT INTO "stickers" (id, pack_id, name, image_url, tags, order_index) VALUES
(
  'ed1b1a7d-2b49-411a-8a48-128a156f0f5b', -- A unique UUID for this sticker.
  'f47ac10b-58cc-4372-a567-0e02b2c3d479', -- The `id` of the pack this sticker belongs to (e.g., 'Greetings').
  'Hello', -- A name for the sticker, used for searching.
  'https://res.cloudinary.com/your-cloud/image/upload/v1/hello-sticker.png', -- The public URL to the sticker image.
  '{"hello", "greeting", "hi"}', -- A list of search tags in PostgreSQL array format.
  1 -- The display order within the pack (1, 2, 3, ...).
),
(
  'a2c4e6f8-3b57-422b-9b59-139b267g1g6c',
  'f47ac10b-58cc-4372-a567-0e02b2c3d479',
  'Goodbye',
  'https://res.cloudinary.com/your-cloud/image/upload/v1/goodbye-sticker.png',
  '{"bye", "see ya", "later"}',
  2
);

-- To add stickers for another pack, create a new INSERT statement:
-- INSERT INTO "stickers" (id, pack_id, name, image_url, tags, order_index) VALUES
-- ('sticker-uuid-3', 'another-uuid-here', 'Awesome', 'https://example.com/sticker3.png', '{"awesome", "cool"}', 1);


RAISE NOTICE 'Your custom sticker data has been successfully inserted.';
