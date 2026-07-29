/** @type {import('@capacitor/cli').CapacitorConfig} */
const config = {
  appId: "com.hmusicandarts.parent",
  appName: "H-Music Parent",
  webDir: "www",
  appendUserAgent: "HMusicParentApp",
  server: {
    url: "https://hmusic-crm.onrender.com/parent_login?native_app=1",
    cleartext: false,
    allowNavigation: [
      "hmusic-crm.onrender.com",
      "checkout.stripe.com",
      "*.stripe.com",
      "*.link.com",
      "connect.squareup.com",
      "connect.squareupsandbox.com",
      "*.squareup.com",
      "square.link",
      "*.square.link",
      "*.square.site"
    ]
  },
  ios: {
    contentInset: "automatic"
  }
};

module.exports = config;
