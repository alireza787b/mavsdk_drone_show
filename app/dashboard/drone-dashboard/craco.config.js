// craco.config.js
const CopyWebpackPlugin = require('copy-webpack-plugin');
const webpack = require('webpack');
const path = require('path');

module.exports = {
  devServer: {
    allowedHosts: 'all',
    client: {
      overlay: false
    }
  },
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
              to: 'static/cesium/Workers'
            },
            {
              from: 'node_modules/cesium/Build/Cesium/ThirdParty',
              to: 'static/cesium/ThirdParty'
            },
            {
              from: 'node_modules/cesium/Build/Cesium/Assets',
              to: 'static/cesium/Assets'
            },
            {
              from: 'node_modules/cesium/Build/Cesium/Widgets',
              to: 'static/cesium/Widgets'
            }
          ]
        }),
        new webpack.DefinePlugin({
          CESIUM_BASE_URL: JSON.stringify('/static/cesium')
        })
      ]
    },
    configure: (webpackConfig) => {
      webpackConfig.output = {
        ...webpackConfig.output,
        globalObject: 'this'
      };

      webpackConfig.module.rules.push({
        test: /\.(js|mjs|jsx)$/,
        enforce: 'pre',
        loader: require.resolve('source-map-loader'),
        resolve: {
          fullySpecified: false
        }
      });

      webpackConfig.ignoreWarnings = [
        ...(webpackConfig.ignoreWarnings || []),
        /Failed to parse source map/
      ];

      return webpackConfig;
    }
  }
};