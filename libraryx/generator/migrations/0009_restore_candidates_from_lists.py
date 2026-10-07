import unicodedata

from django.db import migrations


# Candidates present in the supplied registration report and N3 roster but not
# in the checked-in database snapshot. Status values are (name, class, toge,
# echarpe, frais_soutenance, filiere, niveau).
CANDIDATES = [
    ("BINDJEME BINDJEME BRYAN JAPHET", "SR3B", False, True, True, "SR", "N3"),
    ("NOUTSI MAIVA SIROLLE", "Gl3D", False, True, True, "SR", "N3"),
    ("NEKAM FOKA JOHAN MIGUEL", "Non spécifiée", False, False, True, "SR", "N2"),
    ("TOMBOU FRANCK ARCHANGE", "SR3B", False, False, True, "SR", "N3"),
    ("ATANGANA ALOYS HERVÉ", "Non spécifiée", False, True, True, "SR", "N2"),
    ("YOGO JEAN ARIEL LEPRECIEUX", "BA2B", False, False, True, "SE", "N2"),
    ("GUIFE ARIM JESSICA MARIE", "L2H", False, False, True, "SR", "N2"),
    ("MEKONGO BODO MARIE THÉRÈSE AUDREY", "Non spécifiée", False, False, True, "SR", "N3"),
    ("AYONG MOBITANG HADASSA ROSY", "L2G", False, False, True, "SR", "N2"),
    ("TAYOU KAMGUE ARISTIDE AUDREY", "L2f", False, False, True, "SR", "N2"),
    ("TALOM WILSON CABREL", "SR3A", False, False, True, "SR", "N3"),
    ("JIONGO DONTSOP DUCHEL ANGE", "Non spécifiée", False, False, True, "SR", "N3"),
    ("NLOGA KOMOL DUVARY", "Non spécifiée", False, False, True, "SR", "N2"),
    ("TENE DARYL ORNEL", "Non spécifiée", False, False, True, "SR", "N2"),
    ("KENNE TCHINDA BLERIO", "L2g", False, False, True, "GL", "N2"),
    ("EDZOGO NGONO JUSTICE VINCENT", "BA2C", False, True, True, "SR", "N3"),
    ("NYITOUEKE ASSIENE HANDY", "SE3A", False, False, True, "SE", "N3"),
    ("KAOUDJE LOWE STEVE MARTIAL", "BA2A", False, False, True, "SR", "N2"),
    ("MEKONGO TAKOUTSOP", "L2B", False, True, True, "SR", "N2"),
    ("AKAMSE MANGA ANDY", "L2F", False, False, True, "SR", "N2"),
    ("NDZANA TOBIE KEVIN", "Gl3C", False, True, True, "SR", "N3"),
    ("KONTCHOU YAMDJEU EZECHIEL", "L2D", False, False, True, "GL", "N2"),
    ("IVANNA JOELLE NSANA", "BA2C", False, False, True, "SE", "N2"),
    ("ADE SIMON ANYE", "BA2B", False, False, True, "SE", "N2"),
    ("ZAMBO NGONO JOHAN FRANCK", "BA2B", False, False, True, "SE", "N2"),
    ("AMENDE DANIEL JUNIOR", "L2d", False, False, True, "SR", "N2"),
    # These three names occur only in the Word roster. A blank class is kept
    # unspecified; a class prefix supplies the filière when it is available.
    ("SINOU TAKOUGOUM NGEULE INES", "SE3B", False, False, False, "SE", "N3"),
    ("DEFFO TAKOUDJOUK", "Non spécifiée", False, False, False, "Non spécifiée", "N3"),
    ("DSCHIDA DSAGUE DERRICK", "GL3A", False, False, False, "GL", "N3"),
]


def normalize_name(value):
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", value).casefold()
        if character.isalnum()
    )


def restore_candidates(apps, schema_editor):
    StudentRegistration = apps.get_model("generator", "StudentRegistration")
    existing_names = {
        normalize_name(name)
        for name in StudentRegistration.objects.values_list("full_name", flat=True)
    }

    for name, classe, toge, echarpe, frais_soutenance, filiere, niveau in CANDIDATES:
        key = normalize_name(name)
        if key in existing_names:
            continue
        StudentRegistration.objects.create(
            full_name=name,
            classe=classe,
            toge=toge,
            echarpe=echarpe,
            frais_soutenance=frais_soutenance,
            filiere=filiere,
            niveau=niveau,
        )
        existing_names.add(key)


class Migration(migrations.Migration):
    dependencies = [("generator", "0008_flyeraccesscode")]

    operations = [migrations.RunPython(restore_candidates, migrations.RunPython.noop)]
