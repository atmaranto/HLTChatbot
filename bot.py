"""
The main file for the HLT Chatbot.
 By Anthony Maranto (ATM170000) and Usaid Malik (UXM170001)

"""
import code
import pprint

import nltk
from nltk import sent_tokenize, word_tokenize, pos_tag
from nltk.corpus import wordnet as wn
from nltk.wsd import lesk
import sqlite3
import pickle

import datetime

from utils import advanced_parse, preprocess_db, find_node_by_tag, detokenize, capitalize_all, wnl

class GameBot:
    def __init__(self, db_path="games.sqlite"):
        self.con = sqlite3.connect(db_path)
        self.cur = self.con.cursor()
        self.prepare_state()
    
    def prepare_state(self):
        self.cur.execute("CREATE TABLE IF NOT EXISTS metadata ("
                         "  key TEXT NOT NULL PRIMARY KEY,"
                         "  value TEXT NOT NULL"
                         ");")
    
    def preprocess_facts(self):
        preprocess_db(self.con, self.cur)
    
    def set(self, key : str, value : str):
        # Sets a fact about the current state
        self.cur.execute("INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)", (key, value))
    
    def get(self, key : str, default=None):
        return next(iter(self.cur.execute("SELECT value FROM metadata WHERE key = ?", (key,))), (default,))[0]
    
    def find_games(self, descriptor):
        self.cur.execute("SELECT id, name FROM games WHERE name LIKE ?", (descriptor,))
        result = self.cur.fetchmany()
        
        if len(result) > 0: return result
        
        self.cur.execute("SELECT * FROM games WHERE name LIKE ?", ('%' + descriptor + '%',))
        return self.cur.fetchmany()
    
    def find_game(self, *args, **kwargs):
        return next(iter(self.find_games(*args, **kwargs)), None)
    
    def find_relations(self, **kwargs):
        if len(kwargs) == 0: return []
        
        key_values = list(kwargs.items())
        
        query = "SELECT * FROM relations WHERE " + " AND ".join(key + "=?" for key, _ in key_values) + ";"
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
        
        if command is not None and to is not None:
            # TODO: Change command to be "tell me something"
            fact = self.get_random_fact()
            predicate = (fact[1] + "s") if fact[1] != "be" else "is"
            print(f"Did you know: {fact[0].capitalize()} {predicate} {fact[2]}?")
            print(f"Related to game: {self.find_game_by_id(fact[-2])[1]}")
            return True
        
        return "That doesn't look like a question... we currently only support questions"
    
    def process(self, line):
        """Processes the line of user input"""
        tree, entities, openie, tokens = advanced_parse(line)
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
        
        question = find_node_by_tag(tree, ("WHNP", "WHADVP"))
        if question is None: return "No question word found"
        
        question = detokenize(question.leaves()).lower()
        
        if question not in ("what", "who", "how", "when"): #"when"
            return f"\"{question}\" is not supported"
        
        query = find_node_by_tag(tree, "SQ")
        
        if query is None:
            return "Couldn't find a query in your question"
        
        vb = find_node_by_tag(query, lambda label: label.startswith("VB"), recursive=True)
        
        if vb is None:
            return "Your question doesn't appear to be complete"
        
        predicate = detokenize(vb.leaves())
        predicate_lemma = wnl.lemmatize(predicate, "v")
        
        np = find_node_by_tag(query, "NP")
        
        if np is None:
            return "Couldn't find what you're asking about"
        
        np = detokenize(np.leaves())
        
        ###!!!! USAID!!!###
        # Here is probably where you would potentially want to implement any sort of stuff to handle asking questions
        # about the specific rows we have. The code I have below is mostly related to the arbitrary fact finding that
        # I was implementing. This function returns None on undefined errors, True on success (or handled errors), False
        # when the program should exit, and a string for specific error messages.
        # I recommend printing out question, query, predicate, and np to see what we have to work with. tree contains
        # the entire parse tree.

        results = []
        if question in ("when",):
            # Check release date
            particle = find_node_by_tag(query, "VBN", recursive=True)
            
            if particle is not None and wnl.lemmatize(detokenize(particle.leaves()).lower(), "v") == "release":
                games = self.find_games(np)
                if len(games) == 0:
                    return f"I couldn't find any game called {np}"
                
                for game in games:
                    title = capitalize_all(game[1])
                    
                    if game[2] is not None:
                        results.append(f"{title} was released on {datetime.date.fromtimestamp(game[2])}")
                    else:
                        results.append(f"I don't know when {title} was released")
        elif question in ("how",):
            game = self.find_game(np)
            if game is None:
                return f"I couldn't find any game called {np}"
            
            results = self.find_relations(subject="there", relation="be", game_id=game[0])
        else:
            results = self.find_relations(subject=np, relation=predicate_lemma)
        
        if results:
            self.set("last_game", str(results[-1][-2]))
        
        pprint.pprint(results)
        
        self.con.commit()
        
        return True
    
    def prompt(self):
        line = ''
        
        try:
            print(f"Enter your prompt for {self.__class__.__name__}. Type \"quit\" to quit.")
            
            while not line:
                line = input("> ").strip()
            
            if line.lower().strip(".!") in ["quit", "exit", "q"]:
                return False
        except KeyboardInterrupt:
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
    # code.interact(local=locals())
    bot.loop()
    
    
