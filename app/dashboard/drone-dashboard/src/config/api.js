// src/config/api.js

const getApiConfig = () => {
    const mode = process.env.REACT_APP_API_MODE || 'auto';
    const currentHostname = window.location.hostname;
    const currentProtocol = window.location.protocol;
    
    // Parse proxy domains from env
    const proxyDomains = (process.env.REACT_APP_PROXY_DOMAINS || '')
      .split(',')
      .map(domain => domain.trim())
      .filter(domain => domain);
  
    let useProxy = false;
    
    // Determine connection mode
    switch (mode) {
      case 'direct':
        useProxy = false;
        break;
      case 'proxy':
        useProxy = true;
        break;
      case 'auto':
      default:
        useProxy = proxyDomains.includes(currentHostname);
        break;
    }
  
    if (useProxy) {
      // Proxy mode - use current domain with API path
      const proxyPath = process.env.REACT_APP_PROXY_PATH || '/api';
      return {
        mode: 'proxy',
        baseURL: `${currentProtocol}//${currentHostname}${proxyPath}`,
        description: `Using HTTPS proxy via ${currentHostname}${proxyPath}`
      };
    } else {
      // Direct mode - use server IP:port
      const serverIP = process.env.REACT_APP_SERVER_IP || '100.96.32.75';
      const serverPort = process.env.REACT_APP_SERVER_PORT || '5000';
      return {
        mode: 'direct',
        baseURL: `http://${serverIP}:${serverPort}`,
        description: `Using direct HTTP to ${serverIP}:${serverPort}`
      };
    }
  };
  
  export const API_CONFIG = getApiConfig();
  
  // Debug logging (remove in production)
  console.log('[API Config]', API_CONFIG.description);