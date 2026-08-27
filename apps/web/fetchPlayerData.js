import fs from "fs/promises";
import https from "https";
import { dirname, join } from "path";
import { fileURLToPath } from "url";

const SLEEPER_API_URL = "https://api.sleeper.app/v1/players/nfl";
const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const FILE_PATH = join(__dirname, "public", "nfl_players.json");

function fetchData(url) {
  return new Promise((resolve, reject) => {
    https
      .get(url, (res) => {
        let data = "";

        res.on("data", (chunk) => {
          data += chunk;
        });

        res.on("end", () => {
          resolve(data);
        });
      })
      .on("error", (err) => {
        reject(err);
      });
  });
}

async function main() {
  try {
    console.log("Fetching player data...");
    const data = await fetchData(SLEEPER_API_URL);

    console.log("Writing data to file...");
    await fs.writeFile(FILE_PATH, data);

    console.log("Player data successfully saved to", FILE_PATH);
  } catch (err) {
    console.error("Error:", err.message);
  }
}

main();
