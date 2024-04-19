from gaussian_parse import GaussianParse
from utilities import split_word
import soundfile as sf

from settings import BASE_GRADE
from settings import PITCH_TOLERANCE, MINIMUM_DELTA
from settings import SELECTED_MODEL, CORRECT_LANGUAGE_WEIGHT, CORRECT_TEXT_WEIGHT

import whisper # consider local import to cut down on import time.
import utilities

from analysis import get_pitch_info, devoiced_check, get_bounds, within_bounds, error_calculation


dataset = [
    ("ごぜんです", "午前.wav", 1),
    ("りょかんです", "旅館.wav", 0),
    ("にほんです", "日本.wav", 2),
    ("りょこうです", "旅行.wav", 0),
    ("ねだんです", "値段.wav", 0),
    ("かぞくです", "家族.wav", 1),
    ("しゃちょうです", "社長.wav", 0),
    ("じゆうです", "自由.wav", 2),
    ("しあいです", "試合.wav", 0),
    ("こしょうです", "故障.wav", 0),
    ("よていです", "予定.wav", 0),
    ("じしんです", "地震.wav", 0),
    ("さとうです", "砂糖.wav", 2),
    ("びじゅつです", "美術.wav", 1),
    ("じごくです", "地獄.wav", 3),
    ("とかいです", "都会.wav", 0),
    ("きょねんです", "去年.wav", 1),
    ("にほんです", "二本.wav", 1),
    ("やきゅうです", "野球.wav", 0),
    ("きおんです", "気温.wav", 0),
    ("じぶんです", "自分.wav", 0),
    ("しょどうです", "書道.wav", 1),
    ("よしゅうです", "予習.wav", 0),
    ("さとうです", "佐藤.wav", 1),
    ("きぶんです", "気分.wav", 1),
    ("せかいです", "世界.wav", 1),
    ("しごとです", "仕事.wav", 0),
    ("よほうです", "予報.wav", 0),
    ("しけんです", "試験.wav", 2),
    ("やちんです", "家賃.wav", 1),
    ("じかんです", "時間.wav", 0),
    ("しゃしんです", "写真.wav", 0),
    ("やさいです", "野菜.wav", 0),
    ("こしょうです", "胡椒.wav", 2),
    ("じゅぎょうです", "授業.wav", 1)
]

def preliminary_pronunciation_check(filename, expected_text):
    """Uses whisper to check to see if the base level of pronunciation is good enough to be understood by Speech-to-Text AI.
    Will go through a series of checks to see if some standard expectations are met.
    Currently, those checks are making sure the model detects the spoken language as Japanese, and that the words are transcribed correctly.
    Note that filename and expected_text should be the full phrase, not the individual segmented phrases!
    Override for testing that also returns detected language, and detected phrase."""

    # grade assigned by whisper. starts at 0.
    grade = 0

    model = whisper.load_model(SELECTED_MODEL)

    # load audio and pad/trim it to fit 30 seconds
    audio = whisper.load_audio(filename)
    audio = whisper.pad_or_trim(audio)

    # make log-Mel spectrogram and move to the same device as the model
    mel = whisper.log_mel_spectrogram(audio).to(model.device)

    # detect the spoken language
    _, probs = model.detect_language(mel)
    detected_language = max(probs, key=probs.get)

    # decode the audio
    options = whisper.DecodingOptions()
    result = whisper.decode(model, mel, options)

    # start grading.
    if detected_language == "ja":
        grade += CORRECT_LANGUAGE_WEIGHT
        # result text will only ever be correct if in correct language, so nest.
        if result.text == expected_text:
            grade += CORRECT_TEXT_WEIGHT
        else:
            # japanese detected, incorrect word detected.
            result_hiragana = utilities.text_to_hiragana(result.text)
            expected_hiragana = utilities.text_to_hiragana(expected_text)

            grade += CORRECT_TEXT_WEIGHT * utilities.compare_hiragana_strings(result_hiragana, expected_hiragana)
    else:
        result_romaji = utilities.text_to_romaji(result.text)
        expected_romaji = utilities.text_to_romaji(expected_text)
        grade += CORRECT_LANGUAGE_WEIGHT * utilities.compare_romaji_strings(result_romaji, expected_romaji)

    return grade, detected_language, result.text

def calculate_grade(sf, sf_array, word, word_array, accent_type):
    """Grade the input sound clip given 5 arguments:
    Takes in the sound clip (sf), the full word (word), and the
    pitch accent pattern type.
    Also expects to be passed in a set of parallel arrays that has the sound clips and words broken
    down into its individual mora.
    Override for testing purposes. Returns (coefficient, grade)"""
    grade = 0
    data = preliminary_pronunciation_check(sf, word)
    coefficient = data[0]

    if coefficient != 0: # if it is worth it to grade the sound file
        # start with a base value that will be weighted according to the coefficient found.
        grade += BASE_GRADE
        result = grade_pitch_pattern(soundfiles=sf_array, accent_type=accent_type, word=word_array)
        grade += (100 - BASE_GRADE) * result[0]

    # gamma,
    return (coefficient, grade, data[1], data[2], result[1], result[2], result[3])


def grade_pitch_pattern(soundfiles, accent_type, word):
    """Expects an input of spliced soundfiles that refer to the word.
    For instance, gakusei-desu should be spliced ga-ku-se-i-de-su and passed in an array accordingly.
    accent_type refers to one of the four accent pattern types passed as an integer.
    word should be an array parallel with soundfiles that gives the spliced hiragana string.

    Override for testing purposes. Returns extra information as well."""
    grade = 0
    jump_accuracy = None
    pattern_accuracy = None
    coefficient = None

    pitches = []
    for mora in soundfiles:
        pitches.append(get_pitch_info(mora))

    if accent_type == 0: # heiban
        low_pitch = pitches[0]
        # check if 2nd mora is devoiced or not.
        if devoiced_check(word[1]) and len(word) > 2:
            high_pitch = pitches[2]
        else:
            high_pitch = pitches[1]
        delta = high_pitch - low_pitch

        if delta <= 0:
            jump_accuracy = 0
        elif delta <= MINIMUM_DELTA:
            jump_accuracy = error_calculation(expected=MINIMUM_DELTA, actual=delta)
        else:
            jump_accuracy = 1

        pattern_accuracy = 0
        for pitch in pitches[2:]:
            if within_bounds(high_pitch, PITCH_TOLERANCE, pitch):
                # within the bounds. give perfect grade.
                pattern_accuracy += 1
            elif devoiced_check(word[pitches.index(pitch)]):
                # devoiced check comes before lower/upper bound comparisons
                pattern_accuracy += 1
            else:
                pattern_accuracy += error_calculation(high_pitch, pitch, PITCH_TOLERANCE)

        pattern_accuracy = pattern_accuracy / len(pitches[2:])
        grade = jump_accuracy * pattern_accuracy

    elif accent_type == 1: # high, drops gradually till end.
        high_pitch = pitches[0]

        pattern_accuracy = 0
        for i in range(len(pitches[1:])):
            lower_bound, upper_bound = get_bounds(high_pitch, PITCH_TOLERANCE)
            if pitches[i] <= lower_bound:
                pattern_accuracy += 1
                high_pitch = pitches[i]
            elif devoiced_check(word[i]):
                pattern_accuracy += 1
            else:
                pattern_accuracy += error_calculation(lower_bound, pitches[i])
                high_pitch = pitches[i] # to be kinder with grading, in case they accidentally went up.

        pattern_accuracy = pattern_accuracy / len(pitches[1:])
        grade = pattern_accuracy

    elif accent_type == 2: # low, high then gradually drops till end
        low_pitch = pitches[0]
        # check if 2nd mora is devoiced or not.
        if devoiced_check(word[1]) and len(word) > 2:
            high_pitch = pitches[2]
        else:
            high_pitch = pitches[1]
        delta = high_pitch - low_pitch

        if delta <= 0:
            jump_accuracy = 0
        elif delta <= MINIMUM_DELTA:
            jump_accuracy = error_calculation(expected=MINIMUM_DELTA, actual=delta)
        else:
            jump_accuracy = 1

        pattern_accuracy = 0
        for i in range(len(pitches[2:])):
            lower_bound, upper_bound = get_bounds(high_pitch, PITCH_TOLERANCE)
            if pitches[i] <= lower_bound:
                pattern_accuracy += 1
                high_pitch = pitches[i]
            elif devoiced_check(word[i]):
                pattern_accuracy += 1
            else:
                pattern_accuracy += error_calculation(lower_bound, pitches[i])
                high_pitch = pitches[i] # to be kinder with grading, in case they accidentally went up.
        pattern_accuracy = pattern_accuracy / len(pitches[2:])

        grade = jump_accuracy * pattern_accuracy

    elif accent_type == 3: # low, high, high, then gradually drops till end.
        # requires a word of at least 3 mora to be type 3.
        low_pitch = pitches[0]
        # check if 2nd mora is devoiced or not.
        if devoiced_check(word[1]) and len(word) > 2:
            high_pitch = pitches[2]
            high_pitch2 = pitches[3]
        else:
            high_pitch = pitches[1]
            high_pitch2 = pitches[2]
        delta = high_pitch - low_pitch

        if delta <= 0:
            jump_accuracy = 0
        elif delta <= MINIMUM_DELTA:
            jump_accuracy = error_calculation(expected=MINIMUM_DELTA, actual=delta)
        else:
            jump_accuracy = 1

        pattern_accuracy = 0
        coefficient = error_calculation(high_pitch, high_pitch2, PITCH_TOLERANCE)
        # high_pitch = max(high_pitch, high_pitch2) # nicer algorithm
        high_pitch = high_pitch2 # stricter algorithm

        for i in range(len(pitches[3:])):
            lower_bound, upper_bound = get_bounds(high_pitch, PITCH_TOLERANCE)
            if pitches[i] <= lower_bound:
                pattern_accuracy += 1
                high_pitch = pitches[i]
            elif devoiced_check(word[i]):
                pattern_accuracy += 1
            else:
                pattern_accuracy += error_calculation(lower_bound, pitches[i])
                high_pitch = pitches[i] # to be kinder with grading, in case they accidentally went up.
        pattern_accuracy = pattern_accuracy / len(pitches[2:])

        grade = jump_accuracy * coefficient * pattern_accuracy

    elif accent_type == 4: # low, hi, then drop on end of word (ie. on "de" of "desu")
        # assumes at least 2-mora word + de-su for 4 minimum mora.
        low_pitch = pitches[0]
        # check if 2nd mora is devoiced or not.
        if devoiced_check(word[1]) and len(word) > 2:
            high_pitch = pitches[2]
        else:
            high_pitch = pitches[1]
        delta = high_pitch - low_pitch

        if delta <= 0:
            jump_accuracy = 0
        elif delta <= MINIMUM_DELTA:
            jump_accuracy = error_calculation(expected=MINIMUM_DELTA, actual=delta)
        else:
            jump_accuracy = 1

        pattern_accuracy = 0
        for pitch in pitches[2:-2]: # cut at "desu." hard coded for 2-mora suffix, might need a dynamic approach later.
            if within_bounds(high_pitch, PITCH_TOLERANCE, pitch):
                # within the bounds. give perfect grade.
                pattern_accuracy += 1
            elif devoiced_check(word[pitches.index(pitch)]):
                # devoiced check comes before lower/upper bound comparisons
                pattern_accuracy += 1
            else:
                pattern_accuracy += error_calculation(high_pitch, pitch, PITCH_TOLERANCE)

        # reuse delta to calculate jump down from word to suffix.

        low_pitch = pitches[-2]
        # check if 2nd mora is devoiced or not.
        if devoiced_check(word[-3]):
            high_pitch = pitches[-3]
        else:
            high_pitch = pitches[-3]
        delta = high_pitch - low_pitch

        if delta <= 0:
            jump_accuracy = 0
        elif delta <= MINIMUM_DELTA:
            jump_accuracy += error_calculation(expected=MINIMUM_DELTA, actual=delta)
        else:
            jump_accuracy += 1

        jump_accuracy = jump_accuracy / 2 # average out over two expected jumps.

        # ensure last mora is in expected value compared to 2nd to last mora.
        lower_bound, upper_bound = get_bounds(low_pitch, PITCH_TOLERANCE)
        if pitches[-1] <= lower_bound:
            pattern_accuracy += 1
        elif devoiced_check(word[-1]):
            pattern_accuracy += 1
        else:
            pattern_accuracy += error_calculation(lower_bound, pitches[-1])

        pattern_accuracy = pattern_accuracy / (len(pitches[2:-2]) + 1) # add one for last drop pattern.
        grade = jump_accuracy * pattern_accuracy

    return grade, jump_accuracy, pattern_accuracy, coefficient

def grade(word, accent_type, audio_file):
    sf_array = []
    word_array, mora_length = split_word(word)

    gp = GaussianParse(audio_file, word, mora_length)
    syllable_clips = gp.splice_audio()

    if len(syllable_clips) == mora_length:
        for i, syllable in enumerate(syllable_clips):
            export_filename = "output/" + word[i] + ".wav"
            sf.write(export_filename, syllable, 22050)
            # sf_array.append(syllable)
            sf_array.append(export_filename)
    else:
        print(f"error with {word} -- incorrect syllable split")
        return

    result = calculate_grade(audio_file, sf_array, word, word_array, accent_type)

    coeff = result[0]
    pitch_grade = result[1]
    detected_language = result[2]
    detected_phrase = result[3]
    jump_accuracy = result[4]
    pattern_accuracy = result[5]
    coeff2 = result[6]

    overall_grade = coeff * pitch_grade

    data = (coeff, pitch_grade, overall_grade, detected_language, detected_phrase, jump_accuracy, pattern_accuracy, coeff2)

    return data

def print_grade_info(data):
    word = data[0] # word in hiragana.
    audio_file = "samples/" + data[1] # path to sound file. assumes samples folder is populated.
    accent_type = int(data[2])

    result = grade(word, accent_type, audio_file)
    coeff = result[0]
    pitch_grade = result[1]
    overall_grade = result[2]
    detected_language = result[3]
    detected_phrase = result[4]
    jump_accuracy = result[5]
    pattern_accuracy = result[6]
    coeff2 = result[7]

    result_string = f"""{word} (Type {accent_type}):
Overall grade = {round(overall_grade, 3)}%
Coefficient γ = {round(coeff, 3)}
    Detected language = {detected_language}
    Detected phrase = {detected_phrase}
Pitch grade α = {round(pitch_grade / 100, 3)}
    """

    if jump_accuracy is not None:
        result_string += f"""   Jump accuracy j = {round(jump_accuracy, 3)}
        """

    result_string += f"""Pattern accuracy ρ = {round(pattern_accuracy, 3)}
    """

    if coeff2 is not None:
        result_string += f"""   Coefficient = {round(coeff2, 3)}"""

    print(result_string)

if __name__ == '__main__':
    # individual test.
    print_grade_info(dataset[1])

    # full test
    # for data in dataset:
    #     print_grade_info(data)

    print(dataset[1])