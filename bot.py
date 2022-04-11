"""
The main file for the HLT Chatbot.
 By Anthony Maranto (ATM170000) and Usaid Malik (UXM170001)

"""
import code
import pprint
import sys

import nltk
from nltk import sent_tokenize, word_tokenize, pos_tag
import sqlite3

import datetime

from utils import advanced_parse, preprocess_db, find_node_by_tag, detokenize, capitalize_all, conjugate,\
    remove_tag, and_join, normalize_encoding, wnl

class GameBot:
    def __init__(self, db_path="games.sqlite"):
        self.con = sqlite3.connect(db_path)
        self.cur = self.con.cursor()
        self.prepare_state()
        self.username = None
    
    def prepare_state(self):
        self.cur.execute("CREATE TABLE IF NOT EXISTS metadata ("
                         "  key TEXT NOT NULL PRIMARY KEY,"
                         "  value TEXT NOT NULL"
                         ");")

        self.cur.execute("CREATE TABLE IF NOT EXISTS ascii_names ("
                         "  game_id TEXT NOT NULL PRIMARY KEY,"
                         "  value TEXT NOT NULL,"
                         "  FOREIGN KEY(game_id) REFERENCES games(id)"
                         ");")
        rows = []
        for game in self.cur.execute("SELECT * FROM games WHERE id NOT IN (SELECT game_id FROM ascii_names)"):
            rows.append((game[0], normalize_encoding(game[1])))
        
        if rows:
            self.cur.executemany("INSERT OR REPLACE INTO ascii_names (game_id, value) VALUES(?, ?)", rows)
            self.con.commit()

    def preprocess_facts(self):
        start = next(iter(self.cur.execute("SELECT value FROM metadata_numbers WHERE key = 'bot_preprocess_offset'")), (0,))[0]
        preprocess_db(self.con, self.cur, start=start)
    
    def set(self, key : str, value : str):
        # Sets a fact about the current state
        self.cur.execute("INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)", (key, value))
    
    def get(self, key : str, default=None):
        return next(iter(self.cur.execute("SELECT value FROM metadata WHERE key = ?", (key,))), (default,))[0]
    
    def find_games(self, *descriptors):
        for base_descriptor in descriptors:
            descs = [base_descriptor]
            other = remove_tag(base_descriptor, "PP")
            if other != base_descriptor: descs.append(other)
            
            for descriptor_tree in descs:
                descriptor = detokenize(descriptor_tree.leaves())
                self.cur.execute("SELECT * FROM games WHERE id IN (SELECT game_id FROM ascii_names WHERE value LIKE ?)", (descriptor,))
                result = self.cur.fetchmany()
                
                if len(result) > 0: return result
                
                self.cur.execute("SELECT * FROM games WHERE id IN (SELECT game_id FROM ascii_names WHERE value LIKE ?)", ('%' + descriptor + '%',))
                result = self.cur.fetchmany()
                
                if len(result) > 0: return result
        
        return []
    
    def find_game(self, *args, **kwargs):
        return next(iter(self.find_games(*args, **kwargs)), None)
    
    def get_part_of_franchises(self, game_id):
        franchises = []
        
        for (franch_id,) in self.cur.execute("SELECT franchise_id FROM in_franchise WHERE game_id = ?", (game_id,)):
            franchises.extend(self.cur.execute("SELECT * FROM franchises WHERE id = ?", (franch_id,)))
        
        return franchises
    
    def find_relations(self, **kwargs):
        return self._find_relations("=", **kwargs)
    
    def find_relations_like(self, **kwargs):
        return self._find_relations(" LIKE ", **kwargs)
    
    def _find_relations(self, eq, **kwargs):
        if len(kwargs) == 0: return []
        
        key_values = list(kwargs.items())
        
        query = "SELECT * FROM relations WHERE " + " AND ".join(key + eq + "?" for key, _ in key_values) + ";"
        return list(self.cur.execute(query, tuple(value for _, value in key_values)))
    
    def get_random_fact(self):
        row = next(iter(self.cur.execute("SELECT * FROM relations ORDER BY RANDOM() LIMIT 1;")))
        return row
    
    def find_game_by_id(self, game_id):
        return next(iter(self.cur.execute("SELECT * FROM games WHERE id = ?", (game_id,))), None)
    
    def process_statement(self, tree):
        # Try to process it as a command
        tree = find_node_by_tag(tree, "VP") or tree
        command = find_node_by_tag(tree, "VB")
        to = find_node_by_tag(tree, "NP")
        what = find_node_by_tag(tree, "NP", which=2)
        
        print("Non-question received")
        print(command, to, what)
        
        if command is not None and to is not None:
            # TODO: Change command to be "tell me something"
            command_lemma = wnl.lemmatize(detokenize(command.leaves()).lower())
            to_lemma = wnl.lemmatize(detokenize(to.leaves()).lower())
            
            if what is not None:
                what_lemma = wnl.lemmatize(detokenize(what.leaves()).lower())
                
                if command_lemma in ("tell", "give") and to_lemma in ("me", "I") and "something" in what_lemma:
                    fact = self.get_random_fact()
                    predicate = conjugate(fact[1], fact[0])
                    print(f"Did you know: {fact[0].capitalize()} {predicate} {fact[2]}?")
                    print(f"Related to game: {self.find_game_by_id(fact[-2])[1]}")
                    return True
        
        
        
        return "That doesn't look like a question... we currently only support questions"
    
    def process(self, line):
        """Processes the line of user input"""
        tree, entities, openie, tokens = advanced_parse(line)
        
        print("Entities:")
        pprint.pprint(entities)
        
        tree.pprint()
        
        while len(tree) == 1:
            tree = tree[0]
            if isinstance(tree, (str, bytes)):
                return None
        
        if tree.label() != "SBARQ":
            # TODO: Enable the user to say "I like X" and "I dislike X" or possibly to add arbitrary facts as relations.
            #       I could have game id = 0 for "reality."
            return self.process_statement(tree)
        
        punct = find_node_by_tag(tree, ".")
        if punct is None or detokenize(punct.leaves()) != "?":
            return "Are you sure that's a question? Questions usually end with question marks, don't they?"
        
        question_phrase = find_node_by_tag(tree, ("WHNP", "WHADVP"))
        if question_phrase is None: return "No question word found"
        
        print(question_phrase)
        
        question = find_node_by_tag(question_phrase, lambda tag: tag.startswith("W"))
        question_object = find_node_by_tag(question_phrase, lambda tag: tag.startswith("N"), recursive=True)
        
        question = detokenize(question.leaves()).lower()
        
        if question not in ("what", "which", "who", "how", "when"): #"when"
            return f"\"{question}\" is not supported"
        
        query = find_node_by_tag(tree, "SQ")
        
        if query is None:
            return "Couldn't find a query in your question"
        
        i = 1
        while True:
            vb = find_node_by_tag(query, lambda label: label.startswith("VB"), which=i, recursive=True)
            
            if vb is None:
                return "Your question doesn't appear to be complete"
            
            predicate = detokenize(vb.leaves()).lower()
            predicate_lemma = wnl.lemmatize(predicate, "v")
            
            if predicate_lemma == "do":
                # Probably a particle
                i += 1
            else:
                break
        
        np = find_node_by_tag(query, "NP")
        
        if np is None:
            return "Couldn't find what you're asking about"
        
        np_word = detokenize(np.leaves())

        games = self.find_games(np) # TODO: Include NER
        if len(games) > 0:
            game = games[0]
        else:
            game = None
        
        # Debug
        # print(question, question_object, predicate, np, query)

        results = []
        if question in ("when",):
            # Check release date
            particle = find_node_by_tag(query, "VBN", recursive=True)
            
            if particle is not None and wnl.lemmatize(detokenize(particle.leaves()).lower(), "v") == "release":
                if not games: return f"I couldn't find any game called {np_word}"
                
                for game in games:
                    title = capitalize_all(game[1])
                    
                    if game[2] is not None:
                        results.append(f"{title} was released on {datetime.date.fromtimestamp(game[2])}")
                    else:
                        results.append(f"I don't know when {title} was released")
        elif question in ("how",):
            if game is None:
                return f"I couldn't find any game called {np_word}"
            
            if predicate_lemma == "be":
    
                ind = find_node_by_tag(vb, "NP", which=2)
                ind_lemma = None if ind is None else wnl.lemmatize(detokenize(ind.leaves()).lower(), "n")
                if ind_lemma == "rating":
                    results.append(
                        f"{game[1]} is rated {game[5]}"
                    )
            
            if not results:
                results = self.find_relations_like(subject="there", relation="be", game_id=game[0])
                results = [
                    f"{capitalize_all(result[0])} {result[1]} {result[2]}" for result in results
                ]
        else:
            if question in ("what",):
                if question_object is not None:
                    question_object_word = detokenize(question_object.leaves()).lower()
                    question_object_lemma = wnl.lemmatize(question_object_word, "n")
                    
                    if question_object_lemma == "franchise":
                        if game is None:
                            results.append(f"I couldn't find a game by that name: {np_word}")
                        else:
                            franchises = self.get_part_of_franchises(game[0])
                            
                            results.append(
                                f"{capitalize_all(game[1])} is part of the following franchises:\n" + \
                                and_join(capitalize_all(franchise[1]) for franchise in franchises)
                            )
                    elif question_object_lemma == "story":
                        if game is None:
                            results.append(f"I couldn't find a game by that name: {np_word}")
                        else:
                            results.append(
                                f"The story of {game[1]} is: {game[4]}"
                            )
                    elif question_object_lemma == "description":
                        if game is None:
                            results.append(f"I couldn't find a game by that name: {np_word}")
                        else:
                            results.append(
                                f"The description of {game[1]} is: {game[3]}"
                            )
                    elif question_object_lemma == "rating":
                        if game is None:
                            results.append(f"I couldn't find a game by that name: {np_word}")
                        else:
                            results.append(
                                f"{game[1]} is rated {game[5]}"
                            )
                    elif question_object_lemma == "game":
                        # Example: What [games] are in the Minecraft franchise?
                        pass
                
            if len(results) == 0:
                # Fallback
                results = self.find_relations_like(subject=np, relation=predicate_lemma)
                results = [
                    f"{capitalize_all(result[0])} {conjugate(result[1], result[0])} {result[2]}" for result in results
                ]
        
        #if results:
        #    self.set("last_game", str(results[-1][-2]))
        
        for result in results:
            if isinstance(result, str):
                print(result)
            else:
                pprint.pprint(result)
        if len(results) == 0:
            print("I'm afraid that I don't know much about that.")
        
        self.con.commit()
        
        return True
    
    def ensure_username(self):
        while self.username is None:
            print("No username has been selected. Please enter a valid one-word username.")
            username = input("> ").strip()
            if not username.isalnum() or not username:
                print("That username contains non-alphanumeric characters")
            else:
                print(f"Your name is {username}. Is this correct?")
                
                response = input("Y/n: ").strip().lower()
                if response not in ("no", "n", "not"):
                    self.username = username.lower()
                    print(f"Username selected: {self.username}")
    
    def prompt(self):
        self.ensure_username()
        line = ''
        
        try:
            print(f"Enter your prompt for {self.__class__.__name__}. Type \"quit\" to quit.")
            
            while not line:
                line = input("> ").strip()
            
            if line.lower().strip(".!") in ["quit", "exit", "q"]:
                return False
        except (KeyboardInterrupt, EOFError):
            return False
        
        return line
    
    def loop(self):
        while True:
            text = self.prompt()
            if not text: break
            
            for line in sent_tokenize(text):
                result = self.process(line)
                
                if result is False:
                    break
                elif result is None:
                    print("Invalid input; please try again.")
                elif isinstance(result, str):
                    print(result)

if __name__ == "__main__":
    bot = GameBot()
    # bot.preprocess_facts()
    if "interact" in sys.argv: code.interact(local=locals())
    bot.loop()
    
    
