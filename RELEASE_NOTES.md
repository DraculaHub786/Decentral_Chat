# Release Notes — DecentralChat v0.2.0

## 🚀 Version: `v0.2.0`
**Date:** October 25, 2026  
**Title:** Fullscreen & Multi-Device Adaptive Responsive UI Overhaul

---

### 🌟 Highlights & Major Changes

#### 🖥️ Edge-to-Edge Fullscreen Workspace
- **True Viewport Scaling**: Removed rigid outer letterboxing (`max-width: 1560px`, `padding: 24px 28px`); the workspace now seamlessly occupies 100% of the display (`100vw`, `100dvh`).
- **Fullscreen Mode Toggle**: Added a dedicated one-click Fullscreen toggle button (`⛶` / `⤢`) to the navigation rail, supporting native browser fullscreen mode.
- **Ultra-Wide Ergonomics**: Enforced reading line constraints (`max-width: 1100px; margin: 0 auto;`) inside the message container so lines do not stretch uncomfortably on 1440p, 4K, and 21:9 monitors.

#### 📱 Smartphone Experience (iOS & Android)
- **WhatsApp / Telegram Dual-Screen Flow**:
  - **Chats Overview**: When browsing, the sidebar occupies 100% of the screen above the bottom navigation rail.
  - **Active Conversation**: When a conversation is opened, it automatically expands to 100% full screen, and the bottom nav hides smoothly to maximize space for message history and on-screen keyboards.
- **Dedicated Back Navigation**: Integrated a mobile back button (`‹`) in the chat header to return instantly to the chats list.
- **Fixed Mobile Bottom Navigation**: Anchored navigation bar with touch targets ($\ge 44 \times 44\text{px}$) and iOS home indicator safe area support (`env(safe-area-inset-bottom)`).
- **Native Bottom Sheets**: All modals (Settings, New Chat, Create Group, Contacts, Call History, Media & Files) adapt into native-style bottom sheets with top pull handles on mobile screens.
- **iOS Safari Auto-Zoom Fix**: Form inputs styled with a 16px font size on mobile to prevent automatic viewport zooming on tap.

#### 📟 Tablet & Laptop Adaptability (769px – 1024px)
- **Fluid Layout**: Proportional 3-pane split with compact 60px mini-rail.
- **Collapsible Drawer Sidebar**: Sidebar smoothly collapses to `0px` via the menu toggle (`☰`), giving users full-width chat space whenever needed on tablets and laptops.
- **Fluid Header**: Header margins, padding, and text truncate adaptively to eliminate button wrapping or collision with call controls.

#### 🔍 Browser Zoom Resiliency (50% – 250%)
- **Top-Aligned Flex Centering**: Adjusted `#loginScreen` and `.modal` containers to `align-items: flex-start` with `margin: auto;`. When zoomed in (125%–200%), content taller than the viewport scrolls smoothly from `top: 0` without clipping off-screen.
- **Dynamic Action Buttons**: Converted `.action-buttons` from a fixed grid into a flexible wrapping row so buttons wrap cleanly rather than cutting off when zoomed in.

---

### 📦 Files Changed
- `frontend/styles.css` (490+ additions, complete responsive overhaul)
- `frontend/index.html` (interactive viewport meta, fullscreen button, mobile back button)
- `frontend/app.js` (fullscreen controller, mobile view transitions, orientation/resize synchronizer)
