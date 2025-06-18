// craco.config.js
const CopyWebpackPlugin = require('copy-webpack-plugin');
const webpack = require('webpack');
const path = require('path');

module.exports = {
  webpack: {
    alias: {
      // Point cesium to the correct directory
      cesium: path.resolve(__dirname, 'node_modules/cesium')
    },
    plugins: {
      add: [
        // Copy Cesium Assets, Widgets, and Workers to a static directory
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
        // Define Cesium base URL
        new webpack.DefinePlugin({
          CESIUM_BASE_URL: JSON.stringify('/static/cesium')
        })
      ]
    },
    configure: (webpackConfig) => {
      // Add Cesium to externals to avoid bundling it
      webpackConfig.output = {
        ...webpackConfig.output,
        // Needed for Cesium workers
        globalObject: 'this'
      };

      // Handle .js files in cesium with source maps
      webpackConfig.module.rules.push({
        test: /\.(js|mjs|jsx)$/,
        enforce: 'pre',
        loader: require.resolve('source-map-loader'),
        resolve: {
          fullySpecified: false
        }
      });

      // Ignore source map warnings from Cesium
      webpackConfig.ignoreWarnings = [
        ...(webpackConfig.ignoreWarnings || []),
        /Failed to parse source map/
      ];

      return webpackConfig;
    }
  }
};
