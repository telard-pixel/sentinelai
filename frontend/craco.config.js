const path = require("path");

// "@/..." = src/ (come nel progetto originale di Emergent).
module.exports = {
  webpack: {
    alias: { "@": path.resolve(__dirname, "src") },
  },
};
