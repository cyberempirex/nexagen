class NameGenerator:
    def __init__(self, strategy='alphabet_mix'):
        self.strategy = strategy

    def generate(self, count=1):
        if self.strategy == 'alphabet_mix':
            return [self._generate_alphabet_mix() for _ in range(count)]
        elif self.strategy == 'syllable':
            return [self._generate_syllable() for _ in range(count)]
        elif self.strategy == 'consonant_vowel':
            return [self._generate_consonant_vowel() for _ in range(count)]
        elif self.strategy == 'hybrid':
            return [self._generate_hybrid() for _ in range(count)]
        else:
            raise ValueError("Invalid generation strategy.")

    def _generate_alphabet_mix(self):
        import random
        import string
        length = random.randint(5, 12)
        return ''.join(random.choices(string.ascii_letters, k=length))

    def _generate_syllable(self):
        import random
        syllables = ['ba', 'ka', 'la', 'ra', 'ne', 'mi', 'fu']
        return ''.join(random.choice(syllables) for _ in range(random.randint(2, 4)))

    def _generate_consonant_vowel(self):
        import random
        consonants = 'bcdfghjklmnpqrstvwxyz'
        vowels = 'aeiou'
        name = []
        for _ in range(random.randint(3, 6)):
            name.append(random.choice(consonants))
            name.append(random.choice(vowels))
        return ''.join(name)

    def _generate_hybrid(self):
        import random
        if random.choice([True, False]):
            return self._generate_alphabet_mix()
        else:
            return self._generate_consonant_vowel()