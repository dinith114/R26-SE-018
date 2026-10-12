/**
 * The Firebase app. One instance, shared by the database and by auth.
 *
 * WHY THESE VALUES ARE IN GIT WHILE THE BACKEND KEY IS NOT
 *
 * `secret.js` is gitignored because ORCHID_API_KEY *authorises* writes: holding
 * it lets you start a pump. The values below authorise nothing. A Firebase web
 * API key names a project so the SDK knows which one to talk to, and every
 * request made with it still has to carry a signed ID token that Firebase
 * minted for a real account. Google documents it as public, and it has in any
 * case been sitting in `mobile/google-services.json` in this public repository
 * since August - the same key, byte for byte. Splitting it out now would hide
 * nothing and would break `npm start` for anyone cloning.
 *
 * They are copied from that file rather than typed from the console:
 *   apiKey      client[0].api_key[0].current_key
 *   projectId   project_info.project_id
 *   databaseURL project_info.firebase_url
 * If the project is ever re-created, copy them again from the new
 * google-services.json. Do not hand-edit one and not the other.
 */
import { initializeApp } from 'firebase/app';
import { getDatabase } from 'firebase/database';

const firebaseConfig = {
  apiKey: 'AIzaSyCk5enpArtFDAd54aVraj6kQ8gtVpz9-NY',
  authDomain: 'orchid-smart-care.firebaseapp.com',
  projectId: 'orchid-smart-care',
  databaseURL: 'https://orchid-smart-care-default-rtdb.firebaseio.com',
};

const app = initializeApp(firebaseConfig);
export const database = getDatabase(app);
export default app;
