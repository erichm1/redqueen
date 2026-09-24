from django import forms

from cases.models import Intake
from registry.demo import SCENARIOS
from registry.models import Infraction, Penalty

MAX_UPLOAD_MB = 100


class IntakeForm(forms.Form):
    media = forms.FileField(label='Photo or video')
    precinct = forms.CharField(max_length=64, required=False)

    def clean_media(self):
        media = self.cleaned_data['media']
        if media.size > MAX_UPLOAD_MB * 1024 * 1024:
            raise forms.ValidationError(f'File is larger than {MAX_UPLOAD_MB} MB.')
        return media


class ReviewForm(forms.Form):
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 2}))


class JudgmentForm(forms.Form):
    infraction = forms.ModelChoiceField(queryset=Infraction.objects.none())
    convicted = forms.BooleanField(required=False, label='Record a conviction')
    sentence_kind = forms.ChoiceField(choices=Penalty.Kind.choices, label='Sentence')
    amount = forms.DecimalField(required=False, min_value=0, max_digits=10, decimal_places=2, label='Fine amount')
    hours = forms.IntegerField(required=False, min_value=0, label='Community service hours')
    months = forms.IntegerField(required=False, min_value=0, label='Months')
    rationale = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 2}))

    def __init__(self, *args, person=None, **kwargs):
        super().__init__(*args, **kwargs)
        if person is not None:
            self.fields['infraction'].queryset = person.infractions.filter(status=Infraction.Status.OPEN)
            self.fields['infraction'].label_from_instance = (
                lambda i: f'#{i.pk} {i.category} (severity {i.severity}, {i.occurred_at:%Y-%m-%d})')


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault('widget', MultipleFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single = super().clean
        if isinstance(data, (list, tuple)):
            return [single(item, initial) for item in data]
        return [single(data, initial)]


class EnrollForm(forms.Form):
    MAX_PHOTOS = 5

    full_name = forms.CharField(max_length=255)
    date_of_birth = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    scenario = forms.ChoiceField(choices=[(k, label) for k, (label, _) in SCENARIOS.items()],
                                 label='Dummy record to attach', initial='escalating')
    photos = MultipleFileField(label='Face photos')

    def clean_photos(self):
        photos = self.cleaned_data['photos']
        if len(photos) > self.MAX_PHOTOS:
            raise forms.ValidationError(f'At most {self.MAX_PHOTOS} photos.')
        if any(p.size > 10 * 1024 * 1024 for p in photos):
            raise forms.ValidationError('Each photo must be under 10 MB.')
        return photos
