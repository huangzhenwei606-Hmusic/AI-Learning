/** @type {import('@capacitor/cli').CapacitorConfig} */
const config = {
  appId: "com.hmusicandarts.parent",
  appName: "H-Music",
  webDir: "www",
  appendUserAgent: "HMusicParentIOS",
  server: {
    url: "https://hmusic-crm.onrender.com/parent_login?native_app=1",
    cleartext: false,
    allowNavigation: ["hmusic-crm.onrender.com"]
  },
  ios: {
    contentInset: "automatic"
  }
};

module.exports = config;
