-- Migration: Add firebase_uid column to users table
-- This migration adds support for Firebase authentication

-- Add firebase_uid column to users table
ALTER TABLE users ADD COLUMN IF NOT EXISTS firebase_uid TEXT;

-- Create index on firebase_uid for faster lookups
CREATE INDEX IF NOT EXISTS idx_users_firebase_uid ON users(firebase_uid);

-- Add comment to document the column
COMMENT ON COLUMN users.firebase_uid IS 'Firebase UID for authentication';

-- Update RLS policies if needed (assuming RLS is enabled)
-- Note: You may need to adjust these policies based on your specific requirements

-- Example RLS policy for firebase_uid (uncomment if needed):
-- CREATE POLICY "Users can view their own firebase_uid" ON users
--     FOR SELECT USING (auth.uid()::text = firebase_uid);

-- CREATE POLICY "Users can update their own firebase_uid" ON users
--     FOR UPDATE USING (auth.uid()::text = firebase_uid); 