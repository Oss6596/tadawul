// Cloudflare Worker that forwards every request to the Python web app running in a container.
import { Container, getContainer } from "@cloudflare/containers";

export class IchimokuContainer extends Container {
  defaultPort = 8080;
  // Stop the container after 15 minutes without requests; the next request starts it again.
  sleepAfter = "15m";
}

export default {
  async fetch(request, env) {
    // A single named instance keeps the app's in-memory price cache shared by all visitors.
    return getContainer(env.ICHIMOKU, "main").fetch(request);
  },
};
