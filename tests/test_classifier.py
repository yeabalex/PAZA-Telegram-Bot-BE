"""
Unit tests for the EventClassifier service.
"""

from app.services.classifier.event_classifier import EventClassifier

def test_event_classifier():
    classifier = EventClassifier.get_instance(threshold=0.30)

    # Event 1: Amharic Expo
    amharic_event = (
        "ለአዲስ አመት እየሸመታችሁ የምትዝናኑበት ለአስራ አምስት ቀናት ስለሚቆየውና በአዲስ ኢንተርናሽናል ኮንቬንሽን ሴንተር "
        "ስለሚዘጋጀው አደይ ሁሌ አዲስ ኤክስፖና ፌስቲቫል ልንገራችሁ። ከነሀሴ 21 እስከ ጳጉሜ 5 የሚቆይ ዝግጅት ነው።"
    )
    is_event, score, meta = classifier.classify(amharic_event)
    print(f"Amharic Event -> is_event: {is_event}, score: {score}, meta: {meta}")
    assert is_event is True

    # Event 2: English Concert
    english_event = (
        "Ghion Cozy Cinema Night. The perfect rainy season escape is here! Join us for a magical evening of "
        "Cozy Cinema with Live Piano Music at Golden Tulip Addis Ababa. Date: Thursday, August 6, 2026. Price: 700 birr."
    )
    is_event, score, meta = classifier.classify(english_event)
    print(f"English Event -> is_event: {is_event}, score: {score}, meta: {meta}")
    assert is_event is True

    # Non-Event: General Chat / Personal Opinion
    non_event = (
        "እንደምን አደራችሁ ውድ የቻናላችን ተከታታዮች! ዛሬ አየር ሁኔታው በጣም ደስ ይላል። ሁላችሁም መልካም ቀን ይሁንላችሁ።"
    )
    is_event, score, meta = classifier.classify(non_event)
    print(f"Non-Event -> is_event: {is_event}, score: {score}, meta: {meta}")
    assert is_event is False

    print("\nALL CLASSIFIER TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    test_event_classifier()
