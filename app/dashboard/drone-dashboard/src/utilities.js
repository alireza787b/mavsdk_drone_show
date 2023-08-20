export function getBackendURL() {
    const hostArray = window.location.host.split(":");
    const domain = hostArray[0];
    return `http://${domain}:5000`;
}
