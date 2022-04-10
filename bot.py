"""
The main file for the HLT Chatbot.
 By Anthony Maranto (ATM170000) and Usaid Malik (UXM170001)

"""
import pprint

import nltk
from nltk import sent_tokenize, word_tokenize, pos_tag
from nltk.corpus import wordnet as wn
from nltk.wsd import lesk
import sqlite3
import pickle

from utils import advanced_parse, preprocess_db, find_node_by_tag, detokenize, wnl

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
    
    def find_game(self, descriptor):
        self.cur.execute("SELECT id, name FROM games WHERE name LIKE ? LIMIT 1", (descriptor,))
        result = self.cur.fetchone()
        
        if result is not None: return result
        
        self.cur.execute("SELECT id, name FROM games WHERE name LIKE ? LIMIT 1", ('%' + descriptor + '%',))
        result = self.cur.fetchone()
        
        if result is not None: return result
    
    def find_relations(self, **kwargs):
        if len(kwargs) == 0: return []
        
        key_values = list(kwargs.items())
        
        query = "SELECT * FROM relations WHERE " + " AND ".join(key + "=?" for key, _ in key_values) + ";"
        return list(self.cur.execute(query, (value for _, value in key_values)))
    
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
            return "That doesn't look like a question... we currently only support questions"
        
        punct = find_node_by_tag(tree, ".")
        if punct is None or detokenize(punct.leaves()) != "?":
            return "Are you sure that's a question? Questions usually end with question marks, don't they?"
        
        question = find_node_by_tag(tree, ("WHNP", "WHADVP"))
        if question is None: return "No question word found"
        
        question = detokenize(question.leaves())
        
        if question.lower() not in ("what", "who", "how"): #"when"
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

        if question in ("how",):
            game = self.find_game(np)
            if game is None:
                return f"I couldn't find any game called {np}"
            
            results = self.find_relations(subject="there", relation="be", game_id=game[1])
        else:
            results = self.find_relations(subject=np, relation=predicate_lemma)
        
        pprint.pprint(results)
        if results:
            self.set("last_game", str(results[-1][-2]))

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
    bot.preprocess_facts()
    
    
