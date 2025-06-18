// craco.config.js
const CopyWebpackPlugin = require('copy-webpack-plugin');
const path = require('path');

module.exports = {
  webpack: {
    alias: {
      cesium: path.resolve(__dirname, 'node_modules/cesium')
    },
    plugins: {
      add: [
        new CopyWebpackPlugin({
          patterns: [
            {
              from: 'node_modules/cesium/Build/Cesium/Workers',
              to: 'cesium/Workers',
            },
            {
              from: 'node_modules/cesium/Build/Cesium/ThirdParty',
              to: 'cesium/ThirdParty',
            },
            {
              from: 'node_modules/cesium/Build/Cesium/Assets',
              to: 'cesium/Assets',
            },
            {
              from: 'node_modules/cesium/Build/Cesium/Widgets',
              to: 'cesium/Widgets',
            },
          ],
        }),
      ],
    },
  },
};
