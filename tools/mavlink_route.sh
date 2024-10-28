#!/bin/bash

# mavlink_route.sh
# Enhanced script to configure and start the mavlink-routerd service to route MAVLink traffic
# between various nodes. This version includes default routes and accepts additional endpoints via
# command-line arguments.
#
# Usage:
#   ./mavlink_route.sh [OPTIONS]... [ENDPOINTS]...
#
# Options:
#   -h, --help    Show this help message and exit.
#
# Examples:
#   ./mavlink_route.sh 192.168.1.5:24550
#   This example starts mavlink-routerd routing MAVLink packets from the specified IP endpoint
#   in addition to the pre-programmed endpoints.

# Default listening endpoint
listen_endpoint="0.0.0.0:34550"

# Pre-programmed client endpoints
preprogrammed_clients=(
    "100.84.172.88:24550" # S9 Plus
    "100.84.147.240:24550" # S9
    "100.84.229.96:24550" # Iphone 13s
    "11.94.119.73:24550" # Nokia
    "100.84.20.178:24550" # Macbook 
)

# Function to display help
show_help() {
    echo "Usage: $0 [OPTIONS]... [ENDPOINTS]..."
    echo ""
    echo "Options:"
    echo "  -h, --help    Show this help message and exit."
    echo ""
    echo "Example:"
    echo "  $0 192.168.1.5:24550"
    echo "  This will add the endpoint to the pre-programmed list and start mavlink-routerd."
}

# Check for help option
if [[ "$1" == "-h" || "$1" == "--help" ]]; then
    show_help
    exit 0
fi

# Building the endpoint arguments for mavlink-routerd
endpoints=""
for endpoint in "${preprogrammed_clients[@]}"; do
    endpoints+="-e $endpoint "
done

# Adding command line endpoints to the routing list
for arg in "$@"; do
    endpoints+="-e $arg "
done

# Outputting routing information
echo "Starting mavlink-routerd with the following configuration:"
echo "Listening on: $listen_endpoint"
echo "Routing to the following client endpoints:"
for client in ${preprogrammed_clients[@]} "$@"; do
    echo "  - $client"
done

# Starting mavlink-routerd with the specified endpoints
command="mavlink-routerd $endpoints$listen_endpoint"
echo "Executing: $command"
eval $command
