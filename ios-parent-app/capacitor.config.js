/** @type {import('@capacitor/cli').CapacitorConfig} */
const config = {
  appId: "com.hmusicandarts.parent",
  appName: "H-Music",
  webDir: "www",
  server: {
    url: "https://hmusic-crm.onrender.com/parent_login",
    cleartext: false
  },
  ios: {
    contentInset: "automatic"
  }
};

module.exports = config;
