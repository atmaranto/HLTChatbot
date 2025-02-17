"""
CS4395 Project #2 (assisting script)
Gets video game information from IGDB API and compiles into SQLite3 database. 
Authors: Usaid Malik and Anthony Maranto
"""
import sqlite3
from time import sleep
import requests
from igdb.wrapper import IGDBWrapper  # pip install igdb-api-v4
import json
from tqdm import tqdm  # pip install tqdm

def get_oauth(client_id, client_secret):
    """
    Gets OAuth token from Twitch.
    Args:
        client_id: Client ID associated with dev account
        client_secret: Client Secret associated with dev project
    Returns:
        OAuth access token necessary for API calls
    """
    url = f'https://id.twitch.tv/oauth2/token?client_id={client_id}&client_secret={client_secret}&grant_type=client_credentials'
    result = requests.post(url)
    return result.json()['access_token']

def igdb_request(igdb_wrapper, endpoint, request):
    """
    Performs REST IGDB API call
    Args:
        igdb_wrapper: IGDBWrapper used to compose API requests
        endpoint: API endpoint to sent POST request to
        request: APIpocalypse-formatted request for data
    Returns:
        JSON of data requested from IGDB 
    """
    url = IGDBWrapper._build_url(endpoint)
    params = igdb_wrapper._compose_request(request)
    byte_result = requests.post(url, **params).content
    return json.loads(byte_result.decode('utf-8'))

_db_errors = False
def execute_db_query(connection, query, values=[]):
    global _db_errors
    """
    Performs SQL query on database
    Args:
        connection: SQLite3 DB connection
        query: SQL query
        values (opt): List of values supplised with query
    """
    cursor = connection.cursor()
    try:
        if len(values) == 0:
            cursor.execute(query)
        else:
            cursor.executemany(query, values)
        connection.commit()
    except sqlite3.Error as e:
        print(f'SQL Error {e} occurred in query:\n{query}')
        _db_errors = True

class Franchise:
    """Stores Franchise information"""
    def __init__(self, name, slug):
        self.name = name
        self.slug = slug
        self.games = set()
    
    def __repr__(self) -> str:
        output_str = f'{self.name}\n'
        output_str += '\t'.join([f'{game.name}\n' for game in self.games])
        return output_str

    def add_game(self, game):
        """Adds game to Franchise"""
        self.games.add(game)

class Game:
    """Stores Game information"""
    def __init__(self, name, rating, release_date, storyline, summary, themes, genres, checksum, slug):
        """
        Game constructor
        Args:
            name: Name of game
            rating: Rating of game
            release_date: Release date of game
            storyline: Description of game's plot
            summary: Summary of game
            themes: Themes associated with game
            genres: Genres associated with game
            checksum: IGDB Checksum of game
        """
        self.name = name
        self.rating = rating
        self.release_date = release_date
        self.story = storyline
        self.summary = summary
        self.themes = themes
        self.genres = set(genres)
        self.checksum = checksum
        self.slug = slug

    def __eq__(self, other):
        return self.checksum == other.checksum

    def __hash__(self) -> int:
        return hash(self.checksum)

if '__main__' == __name__:
    from argparse import ArgumentParser
    
    ap = ArgumentParser(description="Downloads game information to the games.sqlite file for use with bot.py")
    
    ap.add_argument("client-id", help="Your Twitch client id for API authentication")
    ap.add_argument("client-secret", help="Your Twitch client secrret for API authentication")
    
    args = ap.parse_args()
    
    # Twitch Client ID/Secret used for API authentication
    client_id = args.client_id
    client_secret = args.client_secret
    
    db_connection = None  # Stores connection to SQL DB
    # Attempt to connect to SQL DB
    try:
        db_connection = sqlite3.connect('games.sqlite')
    except sqlite3.Error as e:
        print('Failed to connect to DB')
    
    # Get authentication token for IGDB API calls
    access_token = get_oauth(client_id, client_secret)
    wrapper = IGDBWrapper(client_id, access_token)
    
    OFFSET = 0
    db_connection.execute("CREATE TABLE IF NOT EXISTS metadata_numbers ("
                          "  key TEXT NOT NULL PRIMARY KEY,"
                          "  value INTEGER"
                          ")")
    OFFSET = next(iter(db_connection.execute("SELECT value FROM metadata_numbers WHERE key = 'offset';")), (OFFSET,))[0]
    
    # Request 500 franchises from IGDB
    franchises = igdb_request(wrapper, 'franchises', f'fields name, slug, games; limit 500; offset {OFFSET};')
    print("Received", len(franchises), "franchises")
    franchise_list = []  # Stores all received Franchises
    genre_set = set()  # Stores all seen genres
    game_map = {}
    query_string = 'fields name, total_rating, category, first_release_date, storyline, summary, themes, genres, slug, checksum; where id = {};'
    # Loop through all Franchises
    iterable = tqdm(franchises)
    for franchise in iterable:
        franchise_games = franchise.get('games', [])
        # Only interested in franchises with 3+ related games
        if len(franchise_games) < 1:
            continue
        franchise_obj = Franchise(franchise['name'], franchise["slug"])
        iterable.set_postfix({"franchise": franchise_obj.name}, False)
        # Get information for every Game related to the Franchise
        game_ids = str(tuple(int(game_id) for game_id in franchise_games)).replace(" ", "") if len(franchise_games) > 1 else str(franchise_games[0])
        this_query = query_string.format(game_ids)
        game_result = igdb_request(wrapper, 'games', this_query)
        # Handle API rate limit
        sleep_timer = 4
        while 'message' in game_result and sleep_timer < 10:
            print('Too many requests, sleeping . . .')
            sleep(sleep_timer)
            sleep_timer += 1
            game_result = igdb_request(wrapper, 'games', query_string.format(this_query))
        if len(game_result) == 0:
            continue
        for game in game_result:
            if game['category'] != 0:  # Not a main game, ignore
                continue
            # Handle possibly-null API data
            if game_map.get(game["slug"]):
                game_obj = game_map[game["slug"]]
            else:
                game_rating = game.get('total_rating', -1)
                game_release_date = game.get('first_release_date', None)
                game_story = game.get('storyline', '')
                game_summary = game.get('summary', '')
                game_themes = game.get('themes', [])
                game_genres = game.get('genres', [])
                game_obj = Game(game['name'], game_rating, game_release_date, game_story, game_summary, game_themes, game_genres, game['checksum'], game["slug"])
                genre_set.update(game_obj.genres)
                game_map[game_obj.slug] = game_obj
            franchise_obj.add_game(game_obj)
        franchise_list.append(franchise_obj)
    
    # Get names of genres using Genre IDs received with Game information
    genre_map = {}
    for genre in genre_set:
        # Do a request to get genre name
        genre_result = igdb_request(wrapper, 'genres', f'fields name, id; where id = {genre};')
        for result in genre_result:
            genre_map[result['id']] = result['name']
    
    # SQL queries to create DB tables
    create_franchise = '''
    CREATE TABLE IF NOT EXISTS franchises (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL
    );
    '''
    create_game = '''
    CREATE TABLE IF NOT EXISTS games (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        release_date INTEGER,
        summary TEXT NOT NULL,
        story TEXT,
        rating REAL
    );
    '''
    create_in_franchise = '''
    CREATE TABLE IF NOT EXISTS in_franchise (
        game_id TEXT NOT NULL,
        franchise_id TEXT NOT NULL,
        FOREIGN KEY(game_id) REFERENCES games(id),
        FOREIGN KEY(franchise_id) REFERENCES franchises(id),
        PRIMARY KEY (franchise_id, game_id)
    )
    '''
    create_in_genre = '''
    CREATE TABLE IF NOT EXISTS in_genre (
        game_id TEXT NOT NULL,
        genre TEXT NOT NULL,
        FOREIGN KEY(game_id) REFERENCES games(id),
        PRIMARY KEY (genre, game_id)
    );
    '''
    # Create DB tables
    #execute_db_query(db_connection, 'DROP TABLE IF EXISTS franchises;')
    #execute_db_query(db_connection, 'DROP TABLE IF EXISTS games;')
    #execute_db_query(db_connection, 'DROP TABLE IF EXISTS in_franchise;')
    #execute_db_query(db_connection, 'DROP TABLE IF EXISTS in_genre;')
    execute_db_query(db_connection, create_franchise)
    execute_db_query(db_connection, create_game)
    execute_db_query(db_connection, create_in_franchise)
    execute_db_query(db_connection, create_in_genre)
    
    # SQL queries to insert data into DB tables
    franchise_insert = '''
    INSERT OR REPLACE INTO
      franchises VALUES (?, ?)
    '''
    game_insert = '''
    INSERT OR REPLACE INTO
      games VALUES (?, ?, ?, ?, ?, ?)
    '''
    in_franchise_insert = '''
    INSERT OR REPLACE INTO
      in_franchise VALUES (?, ?)
    '''
    in_genre_insert = '''
    INSERT OR REPLACE INTO
      in_genre VALUES (?, ?)
    '''

    # Format data into SQLite3-compatible form
    franchise_values = []
    in_franchise = []  # Data to insert into in_franchise table
    in_genre = set()  # Data to insert into in_genre table
    game_values = set()  # Data to insert into games table
    for game in game_map.values():
        summary = game.summary #.replace('\'', '\'\'')
        story = game.story #.replace('\'', '\'\'')
        # Add game, franchise, genres, and game-franchise/game-genre mappings
        game_values.add((game.slug, game.name, game.release_date, summary, story, game.rating))
        
        for genre in game.genres:
            in_genre.add((game.slug, genre_map[genre]))
    
    # Loop through each franchise and add data to corresponding tables
    for franchise in franchise_list:
        franchise_values.append((franchise.slug, franchise.name))
        for game in franchise.games:
            # Escape ' to avoid SQL errors
            in_franchise.append((game.slug, franchise.slug))

    # Insert data into corresponding DB tables
    execute_db_query(db_connection, franchise_insert, franchise_values)
    execute_db_query(db_connection, game_insert, list(game_values))
    execute_db_query(db_connection, in_franchise_insert, in_franchise)
    execute_db_query(db_connection, in_genre_insert, list(in_genre))

    if _db_errors:
        print("Database errors detected; not updating offset metadata")
    else:
        db_connection.execute("INSERT OR REPLACE INTO metadata_numbers (key, value) VALUES('offset', ?);", (OFFSET + 500,))
        db_connection.commit()