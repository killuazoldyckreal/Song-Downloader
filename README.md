# Song Downloader

This Python-based web application allows users to download Spotify songs by song URL or name query.

[Demo](https://spotifydownloader-killua.onrender.com)

## Disclaimer

This website is **not affiliated with or endorsed by Spotify AB**. The use of the name "Spotify" is purely for context and does not imply any ownership or association. All trademarks and copyrights remain the property of their respective owners.

**spotifydownloader-killua.onrender.com does not host any copyrighted material.** Instead, it utilizes third-party services to fetch and process song data. This application simply serves the content retrieved from external APIs (e.g., APIs available on RapidAPI).

This application is intended for **educational and personal use only**. Users should respect copyright and intellectual property rights when downloading and using them.

## Features

### Web Page Setup 
> Implemented a web page interface for users to input Spotify song URLs or names for downloading.

### Metadata Addition 
> Add metadata to songs before delivering the .mp3 files to users, enhancing the overall user experience.

### Security Enhancements 
> Implemented security features like restricted request origins for improved security.

### Environment Variables 
> Stored sensitive information such as API keys and tokens in a separate `.env` file for improved security and ease of configuration.

### Multiple API Setup 
> Configured multiple APIs to fetch songs, providing redundancy and ensuring robustness in case any API fails.

## Requirements

- Python 3.x
- Required Python libraries are listed in the `requirements.txt` file.

## Setup

1. Clone the repository:

   ```bash
   git clone https://github.com/yourusername/spotify-downloader.git
   cd spotify-downloader
   ```

2. Install the required libraries:

   ```bash
   pip install -r requirements.txt
   ```

3. Obtain API credentials:
   - Create a Spotify Developer account and obtain your `CLIENT_ID` and `CLIENT_SECRET`.
   - Leave `MY_API_TOKEN` value empty; its value will keep updating by itself.

4. Set up environment variables by creating a `.env` file in the project root directory and populating it with the following information:

   ```plaintext
   CLIENT_ID="Spotify CLIENT_ID"
   CLIENT_SECRET="Spotify CLIENT_SECRET"
   FLASK_DEBUG=True
   MY_API_TOKEN=""
   ```

5. Run the Flask server:

   ```bash
   python app.py
   ```

## Usage

1. Navigate to the web page and enter the Spotify song URL or name in the provided input field. 
2. Click the "Download" button to initiate the download process.
3. Once the song is downloaded, it will be delivered in .mp3 format with metadata added.

## Acknowledgments

This program uses the following APIs and libraries:
### APIs
- [Spotipy](https://spotipy.readthedocs.io/): Spotify Web API client.

## License

This project is licensed under the [ECL V2.0](LICENSE).
