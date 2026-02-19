from django.db import models
from django.contrib.auth.models import User
from chitti.models import ChittiGroup

class Collector(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    status = models.CharField(max_length=20, choices=(('active','Active'),('inactive','Inactive')))
    groups = models.ManyToManyField(ChittiGroup, related_name='collectors')

    def __str__(self):
        return self.name
